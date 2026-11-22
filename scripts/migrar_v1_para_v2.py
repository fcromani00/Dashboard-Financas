"""Migração da planilha V1 → V2 (mesma planilha, abas novas).

Uso:
    python -m scripts.migrar_v1_para_v2              # só simula: lê, transforma e salva prévias em data/migracao/
    python -m scripts.migrar_v1_para_v2 --aplicar    # cria as abas novas e grava os dados

Garantias:
- As abas antigas (df, Investimentos, Orçamento Financeiro Mensal) NUNCA são alteradas.
- Com --aplicar, aborta se alguma aba nova já tiver dados (use --substituir-abas-novas para recriá-las).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import schema  # noqa: E402
from core.migration import fatiar_orcamento_v1, migrar_tudo  # noqa: E402
from core.sheets import SheetsRepo, abrir_planilha  # noqa: E402

ORDEM_ABAS = [
    "config",
    "contas",
    "categorias",
    "regras",
    "transacoes",
    "importacoes",
    "orcamento",
    "metas",
    "ativos",
    "operacoes",
    "renda_fixa",
    "cotacoes",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--aplicar", action="store_true", help="Cria as abas novas e grava os dados.")
    parser.add_argument("--substituir-abas-novas", action="store_true", help="Apaga e recria abas V2 que já existam.")
    parser.add_argument(
        "--titular",
        action="append",
        default=[],
        help="Nome do titular para detectar transferências entre suas contas (pode repetir). Ex.: --titular 'FELIPE ROMANI'",
    )
    args = parser.parse_args()

    print("Conectando ao Google Sheets...")
    repo = SheetsRepo(abrir_planilha())
    abas = repo.nomes_abas()
    print(f"Abas encontradas: {abas}")

    df_v1 = repo.ler_bruto(schema.V1_TRANSACOES)
    print(f"• '{schema.V1_TRANSACOES}': {len(df_v1)} linhas | colunas: {list(df_v1.columns)}")

    df_inv = None
    if schema.V1_INVESTIMENTOS in abas:
        df_inv = repo.ler_bruto(schema.V1_INVESTIMENTOS)
        print(f"• '{schema.V1_INVESTIMENTOS}': {len(df_inv)} linhas | colunas: {list(df_inv.columns)}")

    blocos = None
    if schema.V1_ORCAMENTO in abas:
        try:
            blocos = fatiar_orcamento_v1(repo.ler_grade(schema.V1_ORCAMENTO))
        except Exception as exc:  # layout diferente do esperado
            print(f"⚠ Não foi possível ler o orçamento V1: {exc}")

    res = migrar_tudo(df_v1, df_inv, blocos, padroes_transferencia=args.titular)

    # ---- prévias locais
    saida = ROOT / "data" / "migracao" / datetime.now().strftime("%Y%m%d_%H%M%S")
    saida.mkdir(parents=True, exist_ok=True)
    for nome, df in res.tabelas.items():
        df.to_csv(saida / f"{nome}.csv", index=False, encoding="utf-8-sig")
    res.relatorio["conferencia_mensal"].to_csv(saida / "_conferencia_mensal.csv", index=False, encoding="utf-8-sig")
    if blocos:
        for nome, df in blocos.items():
            df.to_csv(saida / f"_v1_orcamento_{nome}.csv", index=False, encoding="utf-8-sig")

    # ---- relatório
    print("\n================ RELATÓRIO ================")
    for nome in ORDEM_ABAS:
        print(f"  {nome:<12} {len(res.tabelas[nome]):>6} linhas")
    rel = res.relatorio
    print(f"\n  Transações V1: {rel['qtd_v1']} | V2: {rel['qtd_v2']} | a revisar: {rel['pendentes_revisao']}")
    print(f"  Meses com divergência de total: {rel['meses_divergentes']}")
    if rel["meses_divergentes"]:
        comp = rel["conferencia_mensal"]
        print(comp[~comp["ok"]].to_string(index=False))
    if res.avisos:
        print("\n  Avisos:")
        for a in res.avisos[:30]:
            print(f"   - {a}")
        if len(res.avisos) > 30:
            print(f"   ... (+{len(res.avisos) - 30} avisos)")
    print(f"\n  Prévias salvas em: {saida}")

    if not args.aplicar:
        print("\nSimulação concluída. Nada foi gravado na planilha. Rode com --aplicar para criar as abas V2.")
        return 0

    # ---- aplicar
    if rel["meses_divergentes"]:
        print("\n✗ Há meses com divergência. Corrija antes de aplicar.")
        return 1

    existentes = [n for n in ORDEM_ABAS if n in abas]
    com_dados = [n for n in existentes if len(repo.worksheet(n).get_all_values()) > 1]
    if com_dados and not args.substituir_abas_novas:
        print(f"\n✗ As abas V2 {com_dados} já têm dados. Use --substituir-abas-novas para recriá-las.")
        return 1
    if args.substituir_abas_novas:
        for n in existentes:
            if n in (schema.V1_TRANSACOES, schema.V1_INVESTIMENTOS, schema.V1_ORCAMENTO):
                continue  # proteção extra
            repo.ss.del_worksheet(repo.worksheet(n))
            repo._ws_cache.pop(n, None)

    for nome in ORDEM_ABAS:
        repo.garantir_aba(nome)
        qtd = repo.append(nome, res.tabelas[nome])
        print(f"  ✓ {nome}: {qtd} linhas gravadas")

    print("\n✓ Migração aplicada. As abas antigas continuam intactas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
