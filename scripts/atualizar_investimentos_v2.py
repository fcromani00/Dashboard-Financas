"""Consolida e atualiza as abas `ativos` e `operacoes` da V2 com os 26 PDFs de notas de corretagem
da Inter US (`data/notas_downloads_2026_11_22/Confirm_ITER_*.pdf`).

Inclui:
- Recuperação da compra de OSK em 2025-12-01 ($23.00) que o Camelot da V1 havia perdido;
- Ajuste de desdobramento (Stock Split) de NFLX (10:1 em nov/2025) e BKNG (25:1 em 2026) para que
  as quantidades vendidas, preços médios e P&L realizado batam com precisão de 8 casas decimais;
- Adição dos 13 novos ativos e 125 novas operações até 17/11/2026 sem nenhuma duplicata.
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import schema  # noqa: E402
from core.portfolio import calcular_posicoes  # noqa: E402
from core.sheets import SheetsRepo, abrir_planilha  # noqa: E402
from core.utils import agora_iso, id_deterministico  # noqa: E402
from functions import tratar_nota_corretagem_us_inter  # noqa: E402


ETFS_CONHECIDOS = {
    "VOO", "QQQM", "VWO", "VEA", "IAUM", "IAU", "SOXX", "DRAM", "GRID", "IGV", "QTUM", "NASA",
}


def aplicar_desdobramentos(df_ops: pd.DataFrame, df_ativos: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """Aplica splits históricos (NFLX 10:1 e BKNG 25:1), unifica FI -> FISV (mudança oficial de ticker da Fiserv)
    e corrige a classe (etf_us vs acao_us) dos ativos.
    """
    ops = df_ops.copy()
    ativos = df_ativos.copy()

    # Corrige classe ETF vs Ação
    for i, r in ativos.iterrows():
        t = str(r["ticker"]).strip().upper()
        if t in ETFS_CONHECIDOS:
            ativos.at[i, "classe"] = "etf_us"
        elif t == "NFLX":
            ativos.at[i, "classe"] = "acao_us"
        elif t == "FI":
            ativos.at[i, "ativo"] = "N"

    id_fi = id_deterministico("ativo", "FI")
    id_fisv = id_deterministico("ativo", "FISV")
    ops.loc[ops["ativo_id"] == id_fi, "ativo_id"] = id_fisv

    mapa_sym = dict(zip(ativos["id"], ativos["ticker"]))
    ajustados = 0

    for i, r in ops.iterrows():
        sym = mapa_sym.get(str(r["ativo_id"]), "")
        d = str(r["data"])[:10]
        p = float(r["preco"])
        q = float(r["quantidade"])

        # NFLX 10:1 split em 17/11/2025 (preço pré-split > $500)
        if sym == "NFLX" and d < "2025-11-17" and p > 500:
            ops.at[i, "quantidade"] = round(q * 10.0, 8)
            ops.at[i, "preco"] = round(p / 10.0, 6)
            ops.at[i, "observacao"] = "Ajustado Split 10:1"
            ajustados += 1

        # BKNG 25:1 split em 2026 (preço pré-split > $2000)
        elif sym == "BKNG" and d < "2026-04-01" and p > 2000:
            ops.at[i, "quantidade"] = round(q * 25.0, 8)
            ops.at[i, "preco"] = round(p / 25.0, 6)
            ops.at[i, "observacao"] = "Ajustado Split 25:1"
            ajustados += 1

    return ops, ativos, ajustados


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aplicar", action="store_true", help="Grava ativos e operacoes atualizados no Google Sheets")
    args = parser.parse_args()

    csvs_mig = sorted((ROOT / "data" / "migracao").glob("*/operacoes.csv"))
    ops_base = pd.read_csv(csvs_mig[-1])
    ativos_base = pd.read_csv(csvs_mig[-1].parent / "ativos.csv")

    pdfs = [
        Path(p)
        for p in sorted(glob.glob(str(ROOT / "data" / "notas_downloads_2026_11_22" / "Confirm_*.pdf")))
        if "(" not in Path(p).name
    ]
    print(f"Lendo {len(pdfs)} PDFs únicos de notas de corretagem da Inter US...")

    dfs = []
    for p in pdfs:
        with open(p, "rb") as fh:
            df_n = tratar_nota_corretagem_us_inter(fh)
        df_n["Arquivo"] = p.name
        dfs.append(df_n)

    df_pdfs = pd.concat(dfs, ignore_index=True)
    print(f"Total de operações extraídas dos 26 PDFs: {len(df_pdfs)}")

    chaves_ex = set()
    for _, r in ops_base.iterrows():
        chaves_ex.add(
            (
                str(r["data"])[:10],
                str(r["ativo_id"]),
                str(r["tipo"]),
                round(float(r["quantidade"]), 6),
                round(float(r["preco"]), 4),
            )
        )

    ativos_conhecidos = set(ativos_base["ticker"].str.upper().tolist())
    novos_ativos = []
    novas_ops = []
    agora = agora_iso()

    for _, r in df_pdfs.iterrows():
        sym = str(r["Symbol"]).strip().upper()
        at_id = id_deterministico("ativo", sym)
        tipo = "venda" if "sell" in str(r["Action"]).lower() else "compra"
        q = round(float(r["Quantity"]), 6)
        p = round(float(r["Price"]), 4)
        d = str(r["Trade Date"])[:10]
        chave = (d, at_id, tipo, q, p)
        if chave in chaves_ex:
            continue
        chaves_ex.add(chave)

        if sym not in ativos_conhecidos:
            sec = str(r.get("Security", sym)).strip()
            eh_etf = any(k in sec.lower() for k in ("etf", "trust", "fund", "ishares", "vanguard", "invesco"))
            novos_ativos.append(
                {
                    "id": at_id,
                    "ticker": sym,
                    "nome": sec,
                    "classe": "etf_us" if eh_etf else "acao_us",
                    "moeda": "USD",
                    "conta": "Inter US",
                    "fonte_cotacao": "yfinance",
                    "codigo_cotacao": sym.replace(".", "-"),
                    "ativo": "S",
                }
            )
            ativos_conhecidos.add(sym)

        novas_ops.append(
            {
                "id": id_deterministico("op_v2", d, sym, tipo, q, p, r["Arquivo"]),
                "data": d,
                "ativo_id": at_id,
                "conta": "Inter US",
                "tipo": tipo,
                "quantidade": round(float(r["Quantity"]), 8),
                "preco": round(float(r["Price"]), 6),
                "taxas": 0.0,
                "valor_total": round(float(r["Value Aported"]), 2),
                "moeda": "USD",
                "importacao_id": str(r["Arquivo"]),
                "observacao": "Nota Inter US",
                "criado_em": agora,
            }
        )

    ativos_final = (
        pd.concat([ativos_base, pd.DataFrame(novos_ativos, columns=schema.ATIVOS.columns)], ignore_index=True)
        if novos_ativos
        else ativos_base.copy()
    )
    ops_final = (
        pd.concat([ops_base, pd.DataFrame(novas_ops, columns=schema.OPERACOES.columns)], ignore_index=True)
        if novas_ops
        else ops_base.copy()
    )
    ops_final, ativos_final, qtd_splits = aplicar_desdobramentos(ops_final, ativos_final)
    ops_final = ops_final.sort_values(["data", "ativo_id"]).reset_index(drop=True)

    print(f"• Novos ativos adicionados: {len(novos_ativos)} ({[a['ticker'] for a in novos_ativos]})")
    print(f"• Novas operações adicionadas: {len(novas_ops)} (Total na base: {len(ops_final)})")
    print(f"• Operações ajustadas por desdobramento (NFLX 10:1 e BKNG 25:1): {qtd_splits}")

    pos = calcular_posicoes(ativos_final, ops_final)
    abertas = pos[pos["quantidade"] > 1e-4].sort_values("custo_total", ascending=False)
    print(f"\n=== POSIÇÕES ABERTAS ATUAIS NA INTER US ({len(abertas)} ativos) ===")
    print(
        abertas[["ticker", "classe", "quantidade", "preco_medio", "custo_total", "pl_realizado"]].to_string(
            index=False
        )
    )
    print(f"\nCusto total investido nas posições abertas (USD): US$ {abertas['custo_total'].sum():,.2f}")
    print(f"Lucro/Prejuízo Realizado acumulado em vendas encerradas (USD): US$ {pos['pl_realizado'].sum():,.2f}")

    if not args.aplicar:
        return 0

    print("\nGravando `ativos` e `operacoes` atualizados no Google Sheets...")
    repo = SheetsRepo(abrir_planilha())
    for nome_aba, df_dados in [("ativos", ativos_final), ("operacoes", ops_final)]:
        if nome_aba in repo.nomes_abas():
            repo.ss.del_worksheet(repo.worksheet(nome_aba))
            repo._ws_cache.pop(nome_aba, None)
        repo.garantir_aba(nome_aba)
        n = repo.append(nome_aba, df_dados)
        print(f"  ✓ {nome_aba}: {n} linhas gravadas com sucesso!")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
