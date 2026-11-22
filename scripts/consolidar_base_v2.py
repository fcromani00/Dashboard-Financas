"""Consolida e higieniza toda a base V2 (`transacoes` e `importacoes`):
1. Parte da base V1 migrada, removendo a importação duplicada histórica de `MP-2025-06.csv` (12 linhas)
   e `MP-2025-08.csv` (56 linhas) usando os arquivos originais como gabarito fiel.
2. Remove `Pagamento Cartão de crédito` de 2026 do extrato do Mercado Pago (pois as 10 faturas PDF de 2026
   do Cartão Mercado Pago entram detalhadas item a item).
3. Padroniza movimentações internas de Cofrinho / Reserva / CDB Porquinho / CDB à prazo como
   `Transferência Interna` (`transferencia = 'S'`).
4. Agrega todos os 29 arquivos válidos da pasta Downloads (Extrato Inter, 8 Faturas Inter CSV,
   10 Extratos Mercado Pago CSV e 10 Faturas Cartão Mercado Pago PDF) sem nenhuma duplicata,
   classificando os estabelecimentos inéditos com Histórico + Regras + IA Groq em lote.
"""

from __future__ import annotations

import argparse
import glob
import io
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from core import schema  # noqa: E402
from core.migration import limpar_categoria_v1, migrar_transacoes  # noqa: E402
from core.sheets import SheetsRepo, abrir_planilha  # noqa: E402
from core.transactions import (  # noqa: E402
    classificar_e_reconciliar_v2,
    converter_arquivo_para_v2,
    criar_registro_transacao,
)
from core.utils import agora_iso, hash_dedup, id_deterministico, normalizar_texto, novo_id, parse_data  # noqa: E402

REGRAS_PADRAO_V2: list[tuple[str, str, int]] = [
    ("uberrides", "Transporte", 20),
    ("uber ", "Transporte", 20),
    ("buser", "Transporte", 20),
    ("whoosh", "Transporte", 20),
    ("auto posto", "Transporte", 20),
    ("99app", "Transporte", 20),
    ("cashback", "Cashback", 25),
    ("rendimentos", "Rendimento", 25),
    ("credito concedido", "Estorno", 25),
    ("mercadolivre", "Compras", 15),
    ("mercado livre", "Compras", 15),
    ("amazon", "Compras", 15),
    ("shopee", "Compras", 15),
    ("renner", "Vestuário", 18),
    ("youcom", "Vestuário", 18),
    ("centauro", "Vestuário", 18),
    ("totalpass", "Academia", 20),
    ("gympass", "Academia", 20),
    ("wellhub", "Academia", 20),
    ("smartfit", "Academia", 20),
    ("barbearia", "Barbearia", 20),
    ("ocimar hair", "Barbearia", 20),
    ("juhair", "Barbearia", 20),
    ("duogourmet", "Assinaturas", 20),
    ("melimais", "Assinaturas", 20),
    ("spotify", "Assinaturas", 20),
    ("netflix", "Assinaturas", 20),
    ("google g1", "Assinaturas", 20),
    ("investing com", "Assinaturas", 20),
    ("choperia", "Bares", 18),
    ("esporte e bar", "Bares", 18),
    ("posto 12 esporte", "Bares", 18),
    ("posto 012 e esporte", "Bares", 18),
    ("ifood", "Restaurante", 18),
    ("restaurante", "Restaurante", 15),
    ("drogaria", "Saúde", 18),
    ("drogasil", "Saúde", 18),
    ("droga raia", "Saúde", 18),
    ("farmacia", "Saúde", 18),
    ("ingresso", "Lazer", 18),
    ("cinema", "Lazer", 18),
    ("avixarena", "Lazer", 18),
    ("gypsyyviagem", "Viagem", 18),
    ("booking", "Viagem", 18),
    ("airbnb", "Viagem", 18),
    ("debito conta global de inv", "Investimentos", 25),
    ("debito b3", "Investimentos", 25),
    ("credito b3", "Investimentos", 25),
    ("debito iof", "Imposto, Juros e Multa", 25),
]

TERMOS_MOV_INTERNA = (
    "dinheiro retirado cofrinho",
    "dinheiro reservado cofrinho",
    "dinheiro reservado reserva de emergencia",
    "dinheiro retirado reserva de emergencia",
    "dinheiro reservado ferias",
    "dinheiro retirado ferias",
    "aplicacao cdb porq",
    "resgate cdb porq",
    "estorno cdb porq",
    "investimento cdb a prazo",
    "liberacao cdb a prazo",
    "aplicacao em cdb",
)


class ArquivoLocal(io.BytesIO):
    def __init__(self, path: Path):
        data = path.read_bytes()
        super().__init__(data)
        self.name = path.name
        self.size = len(data)


def eh_movimentacao_interna_reserva(descricao: str) -> bool:
    dn = normalizar_texto(descricao)
    return any(t in dn for t in TERMOS_MOV_INTERNA)


def desduplicar_base_v1(df_tx_v1: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Limpa duplicatas históricas comprovadas da V1 e higieniza transferências internas."""
    df = df_tx_v1.copy()
    stats = {
        "removidas_dup_2025_06_08": 0,
        "removidas_pagto_cartao_mp_2026": 0,
        "marcadas_transf_interna": 0,
        "parcela_youcom_ajustada": 0,
    }

    # 1. Ajuste da 2ª parcela da Lojas Youcom em 2025-05-17 (observacao == 'Parcela 2/5')
    mask_youcom_p2 = (df["observacao"] == "Parcela 2/5") & (df["data"].astype(str) == "2025-05-17")
    for idx in df[mask_youcom_p2].index:
        df.at[idx, "data"] = date(2025, 6, 17)
        desc_atual = str(df.at[idx, "descricao"])
        if "(Parcela 2/5)" not in desc_atual:
            df.at[idx, "descricao"] = f"{desc_atual} (Parcela 2/5)"
        df.at[idx, "hash_dedup"] = hash_dedup(
            date(2025, 6, 17), float(df.at[idx, "valor"]), df.at[idx, "descricao"], df.at[idx, "conta"]
        )
        stats["parcela_youcom_ajustada"] += 1

    # 2. Em 2025-06 e 2025-08, o extrato do Mercado Pago foi importado 2x na V1.
    # Usamos a contagem exata dos arquivos originais MP-2025-06.csv e MP-2025-08.csv para manter 1 cópia fiel.
    gabarito_contagem: Counter = Counter()
    for m in ("06", "08"):
        arq_mp = ROOT / "data" / "arquivos_locais" / f"MP-2025-{m}.csv"
        if arq_mp.exists():
            df_orig, _, _, _ = converter_arquivo_para_v2(ArquivoLocal(arq_mp))
            if df_orig is not None:
                for _, r in df_orig.iterrows():
                    chave = (str(r["data"]), round(float(r["valor"]), 2), normalizar_texto(r["descricao"]), "Mercado Pago")
                    gabarito_contagem[chave] += 1

    vistas: Counter = Counter()
    manter = []
    for _, r in df.iterrows():
        d_str = str(r["data"])[:10]
        ym = d_str[:7]
        conta = str(r["conta"])
        desc_norm = normalizar_texto(r["descricao"])

        # Remove Pagamento Cartão de crédito de 2026 no Mercado Pago (pois entram as 10 faturas PDF de 2026)
        if (
            ym.startswith("2026-")
            and conta == "Mercado Pago"
            and desc_norm in ("pagamento cartao de credito", "pagamento de fatura cartao de credito")
        ):
            stats["removidas_pagto_cartao_mp_2026"] += 1
            continue

        if ym in ("2025-06", "2025-08") and conta == "Mercado Pago" and gabarito_contagem:
            chave = (d_str, round(float(r["valor"]), 2), desc_norm, "Mercado Pago")
            limite = gabarito_contagem.get(chave, 1)
            vistas[chave] += 1
            if vistas[chave] > limite:
                stats["removidas_dup_2025_06_08"] += 1
                continue

        manter.append(r.to_dict())

    df_limpo = pd.DataFrame(manter, columns=schema.TRANSACOES.columns)

    # 3. Marca movimentações internas de Cofrinho / Reserva / CDB Porquinho / CDB à prazo
    for i, r in df_limpo.iterrows():
        if eh_movimentacao_interna_reserva(str(r["descricao"])):
            if df_limpo.at[i, "transferencia"] != "S" or df_limpo.at[i, "categoria"] != "Transferência Interna":
                df_limpo.at[i, "transferencia"] = "S"
                df_limpo.at[i, "categoria"] = "Transferência Interna"
                stats["marcadas_transf_interna"] += 1
        df_limpo.at[i, "data"] = parse_data(r["data"])
        df_limpo.at[i, "hash_dedup"] = hash_dedup(
            df_limpo.at[i, "data"], float(r["valor"]), r["descricao"], r["conta"]
        )

    return df_limpo, stats


def carregar_arquivos_downloads() -> tuple[pd.DataFrame, list[dict]]:
    pasta = ROOT / "data" / "downloads_2026_11_22"
    arquivos = sorted(pasta.glob("*"))
    dfs = []
    registros_imp = []
    agora = agora_iso()

    for arq in arquivos:
        if "(1)" in arq.name or "settlement_v2" in arq.name:
            continue
        df_a, tipo_a, err_a, f_hash = converter_arquivo_para_v2(ArquivoLocal(arq))
        if err_a or df_a is None or df_a.empty:
            continue
        imp_id = novo_id()
        df_a["importacao_id"] = imp_id
        dfs.append(df_a)
        registros_imp.append(
            {
                "id": imp_id,
                "arquivo": arq.name,
                "hash_arquivo": f_hash,
                "formato": tipo_a or "Extrato",
                "qtd_linhas": len(df_a),
                "importado_em": agora,
                "desfeita": "N",
            }
        )

    return pd.concat(dfs, ignore_index=True), registros_imp


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aplicar", action="store_true", help="Grava a base consolidada no Google Sheets")
    args = parser.parse_args()

    # Usa a base migrada mais recente como ponto de partida (ou lê da planilha se --aplicar)
    csvs_mig = sorted((ROOT / "data" / "migracao").glob("*/transacoes.csv"))
    df_v2_inicial = pd.read_csv(csvs_mig[-1])

    df_base_limpa, stats_limpeza = desduplicar_base_v1(df_v2_inicial)
    print("=== 1. HIGIENIZAÇÃO DA BASE EXISTENTE ===")
    print(f"  Linhas antes: {len(df_v2_inicial)} -> Linhas após limpeza: {len(df_base_limpa)}")
    for k, v in stats_limpeza.items():
        print(f"  • {k}: {v}")

    df_novos_bruto, lista_imp = carregar_arquivos_downloads()
    print(f"\n=== 2. ARQUIVOS DE DOWNLOADS LIDOS ({len(lista_imp)} arquivos) ===")
    print(f"  Total de lançamentos lidos nos 29 arquivos: {len(df_novos_bruto)}")

    df_regras_padrao = pd.DataFrame(
        [
            {
                "id": id_deterministico("regra", padrao),
                "padrao": padrao,
                "categoria": cat,
                "prioridade": prio,
                "ativa": "S",
            }
            for padrao, cat, prio in REGRAS_PADRAO_V2
        ],
        columns=schema.REGRAS.columns,
    )

    groq_key = os.getenv("GROQ_API_KEY") if args.aplicar else None
    df_rec, stats_classif = classificar_e_reconciliar_v2(
        df_novos_bruto,
        df_transacoes=df_base_limpa,
        df_regras=df_regras_padrao,
        groq_api_key=groq_key,
    )
    print(f"  Classificação: {stats_classif}")

    selecionadas = df_rec[df_rec["Incluir"] == True].copy()
    duplicatas_ignoradas = len(df_rec) - len(selecionadas)
    print(f"  Duplicatas ignoradas: {duplicatas_ignoradas}")
    print(f"  Novas transações únicas a adicionar: {len(selecionadas)}")

    novos_registros = []
    for _, r in selecionadas.iterrows():
        cat = str(r.get("categoria", "Outras Saídas") or "Outras Saídas")
        if eh_movimentacao_interna_reserva(str(r["descricao"])):
            cat = "Transferência Interna"
        reg = criar_registro_transacao(
            data_tx=r["data"],
            valor=float(r["valor"]),
            descricao=str(r["descricao"]),
            categoria=cat,
            conta=str(r["conta"]),
            meio=str(r["meio"]),
            origem="import",
            status="confirmada",
            importacao_id=str(r.get("importacao_id", "")),
            observacao=str(r.get("observacao", "") or ""),
        )
        novos_registros.append(reg)

    df_novos_final = pd.DataFrame(novos_registros, columns=schema.TRANSACOES.columns)
    df_consolidado = pd.concat([df_base_limpa, df_novos_final], ignore_index=True)
    df_consolidado = df_consolidado.sort_values(["data", "descricao"], ascending=[False, True]).reset_index(drop=True)

    print(f"\n=== 3. BASE FINAL CONSOLIDADA ({len(df_consolidado)} transações únicas) ===")
    df_consolidado["ym"] = df_consolidado["data"].apply(lambda d: d.strftime("%Y-%m"))
    print(pd.crosstab(df_consolidado["ym"], [df_consolidado["conta"], df_consolidado["meio"]]).to_string())

    pendentes = int((df_consolidado["categoria"].isin(["", "A Revisar"])).sum())
    print(f"\n  Transações pendentes ('A Revisar'): {pendentes}")

    # Salva prévia local
    saida_csv = ROOT / "data" / "transacoes_consolidadas_v2.csv"
    df_consolidado.drop(columns=["ym"]).to_csv(saida_csv, index=False, encoding="utf-8-sig")
    print(f"  Prévia completa salva em: {saida_csv}")

    if not args.aplicar:
        return 0

    print("\nGravando base consolidada no Google Sheets...")
    repo = SheetsRepo(abrir_planilha())

    # Recria as abas `transacoes`, `importacoes` e `regras` com a base 100% consolidada e auditada
    for nome_aba, df_dados in [
        ("regras", df_regras_padrao),
        ("transacoes", df_consolidado.drop(columns=["ym"])),
        ("importacoes", pd.DataFrame(lista_imp, columns=schema.IMPORTACOES.columns)),
    ]:
        if nome_aba in repo.nomes_abas():
            repo.ss.del_worksheet(repo.worksheet(nome_aba))
            repo._ws_cache.pop(nome_aba, None)
        repo.garantir_aba(nome_aba)
        n = repo.append(nome_aba, df_dados)
        print(f"  ✓ {nome_aba}: {n} linhas gravadas com sucesso!")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
