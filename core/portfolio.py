"""Motor de Investimentos V2:
- Cálculo correto de posição (compra, venda, dividendo, aporte, resgate, ajuste de saldo)
- Preço médio ponderado, P&L realizado e não realizado
- Estimativa de Renda Fixa por CDI (Banco Central SGS série 12) + ajuste manual
- Cotações em lote via yfinance (Ações/ETFs US, B3 .SA, BTC-BRL e câmbio USDBRL=X)
- Consolidação de patrimônio em BRL
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from core.utils import agora_iso, novo_id, parse_data, parse_numero, vazio


def calcular_posicoes(df_ativos: pd.DataFrame, df_operacoes: pd.DataFrame) -> pd.DataFrame:
    """Calcula a posição atual de cada ativo a partir do livro de operações (`operacoes`)."""
    if df_ativos is None or df_ativos.empty:
        return pd.DataFrame()

    ops = df_operacoes.copy() if df_operacoes is not None and not df_operacoes.empty else pd.DataFrame()
    if not ops.empty:
        ops["data_dt"] = ops["data"].apply(parse_data)
        ops = ops.sort_values(["data_dt", "criado_em"], ascending=[True, True])

    resultados = []
    for _, ativo in df_ativos.iterrows():
        if str(ativo.get("ativo", "S")).upper() == "N":
            continue
        ativo_id = str(ativo["id"])
        classe = str(ativo.get("classe", "acao_us"))
        moeda = str(ativo.get("moeda", "USD"))
        ops_ativo = ops[ops["ativo_id"] == ativo_id] if not ops.empty else pd.DataFrame()

        qtd = 0.0
        custo_total = 0.0
        pl_realizado = 0.0
        proventos = 0.0
        ultimo_ajuste_data: date | None = None
        valor_renda_fixa = 0.0

        for _, op in ops_ativo.iterrows():
            tipo = str(op.get("tipo", "compra")).lower()
            q = abs(parse_numero(op.get("quantidade")) or 0.0)
            p = parse_numero(op.get("preco")) or 0.0
            taxas = abs(parse_numero(op.get("taxas")) or 0.0)
            vt = parse_numero(op.get("valor_total"))
            if vt is None:
                vt = q * p

            if classe == "renda_fixa":
                # Para renda fixa (Porquinho Inter / CDB MP), operamos por saldo financeiro em BRL
                if tipo in ("aporte", "compra"):
                    valor_renda_fixa += abs(vt)
                    custo_total += abs(vt)
                    qtd = 1.0 if valor_renda_fixa > 0 else 0.0
                elif tipo in ("resgate", "venda"):
                    val_resg = abs(vt)
                    if valor_renda_fixa > 0:
                        prop = min(1.0, val_resg / valor_renda_fixa)
                        custo_reduzido = custo_total * prop
                        pl_realizado += val_resg - custo_reduzido
                        custo_total = max(0.0, custo_total - custo_reduzido)
                        valor_renda_fixa = max(0.0, valor_renda_fixa - val_resg)
                    qtd = 1.0 if valor_renda_fixa > 0.01 else 0.0
                elif tipo in ("rendimento", "juros", "dividendo"):
                    valor_renda_fixa += abs(vt)
                    proventos += abs(vt)
                elif tipo == "ajuste_saldo":
                    # Crava o saldo líquido atual informado pelo app do banco
                    novo_saldo = abs(vt) if vt else abs(p)
                    valor_renda_fixa = novo_saldo
                    if custo_total == 0:
                        custo_total = novo_saldo
                    ultimo_ajuste_data = parse_data(op.get("data"))
                    qtd = 1.0 if valor_renda_fixa > 0.01 else 0.0
            else:
                if tipo in ("compra", "aporte"):
                    custo_total += (q * p) + taxas
                    qtd += q
                elif tipo in ("venda", "resgate"):
                    if qtd > 1e-9:
                        pm = custo_total / qtd
                        q_vendida = min(qtd, q)
                        receita_liq = (q_vendida * p) - taxas
                        custo_baixado = q_vendida * pm
                        pl_realizado += receita_liq - custo_baixado
                        qtd -= q_vendida
                        custo_total = max(0.0, custo_total - custo_baixado)
                        if qtd < 1e-7:
                            qtd = 0.0
                            custo_total = 0.0
                elif tipo in ("dividendo", "juros", "rendimento"):
                    proventos += abs(vt) - taxas
                elif tipo == "taxa":
                    pl_realizado -= abs(vt or taxas)

        preco_medio = (custo_total / qtd) if (classe != "renda_fixa" and qtd > 1e-7) else custo_total

        resultados.append(
            {
                "ativo_id": ativo_id,
                "ticker": str(ativo.get("ticker", "")),
                "nome": str(ativo.get("nome", "")),
                "classe": classe,
                "moeda": moeda,
                "conta": str(ativo.get("conta", "")),
                "fonte_cotacao": str(ativo.get("fonte_cotacao", "yfinance")),
                "codigo_cotacao": str(ativo.get("codigo_cotacao", "")),
                "quantidade": round(qtd, 8),
                "preco_medio": round(preco_medio, 6),
                "custo_total": round(custo_total, 2),
                "valor_rf_base": round(valor_renda_fixa, 2),
                "ultimo_ajuste_rf": ultimo_ajuste_data,
                "pl_realizado": round(pl_realizado, 2),
                "proventos": round(proventos, 2),
            }
        )

    return pd.DataFrame(resultados)


def buscar_cotacoes_atuais(codigos_yf: list[str]) -> dict[str, tuple[float, float]]:
    """Busca preço atual e variação % do dia para uma lista de códigos do Yahoo Finance."""
    import yfinance as yf

    codigos = sorted({c.strip() for c in codigos_yf if c and c.strip() and c != "CDI"})
    if "USDBRL=X" not in codigos:
        codigos.append("USDBRL=X")

    precos: dict[str, tuple[float, float]] = {}
    try:
        dados = yf.download(codigos, period="5d", progress=False, group_by="ticker", auto_adjust=True)
        if dados is None or dados.empty:
            return precos

        if len(codigos) == 1:
            c = codigos[0]
            s = dados["Close"].dropna()
            if not s.empty:
                atual = float(s.iloc[-1])
                ant = float(s.iloc[-2]) if len(s) > 1 else atual
                var_pct = ((atual - ant) / ant * 100.0) if ant else 0.0
                precos[c] = (atual, var_pct)
        else:
            for c in codigos:
                try:
                    s = dados[c]["Close"].dropna()
                    if not s.empty:
                        atual = float(s.iloc[-1])
                        ant = float(s.iloc[-2]) if len(s) > 1 else atual
                        var_pct = ((atual - ant) / ant * 100.0) if ant else 0.0
                        precos[c] = (atual, var_pct)
                except Exception:
                    continue
    except Exception:
        pass
    return precos


def consolidar_carteira(
    df_ativos: pd.DataFrame,
    df_operacoes: pd.DataFrame,
    precos_yf: dict[str, tuple[float, float]] | None = None,
    usd_brl_fallback: float = 5.80,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Calcula valor de mercado, P&L e alocação consolidada em BRL para todas as posições abertas."""
    pos = calcular_posicoes(df_ativos, df_operacoes)
    if pos.empty:
        return pd.DataFrame(), {"patrimonio_brl": 0.0, "custo_brl": 0.0, "pl_aberto_brl": 0.0, "usd_brl": usd_brl_fallback}

    abertas = pos[(pos["quantidade"] > 1e-7) | (pos["valor_rf_base"] > 0.01)].copy()
    if abertas.empty:
        return pd.DataFrame(), {"patrimonio_brl": 0.0, "custo_brl": 0.0, "pl_aberto_brl": 0.0, "usd_brl": usd_brl_fallback}

    codigos = abertas[abertas["fonte_cotacao"] == "yfinance"]["codigo_cotacao"].tolist()
    precos = precos_yf if precos_yf is not None else buscar_cotacoes_atuais(codigos)
    usd_brl = precos.get("USDBRL=X", (usd_brl_fallback, 0.0))[0]

    precos_atuais = []
    vars_dia = []
    valores_moeda = []
    valores_brl = []
    custos_brl = []
    pls_moeda = []
    pls_pct = []

    for _, r in abertas.iterrows():
        classe = r["classe"]
        moeda = r["moeda"]
        custo = float(r["custo_total"])
        fator_fx = usd_brl if moeda == "USD" else 1.0

        if classe == "renda_fixa":
            p_atual = float(r["valor_rf_base"])
            var_d = 0.0
            val_m = p_atual
        else:
            cod = r["codigo_cotacao"] or r["ticker"]
            p_atual, var_d = precos.get(cod, (float(r["preco_medio"]), 0.0))
            val_m = float(r["quantidade"]) * p_atual

        pl_m = val_m - custo
        pl_p = (pl_m / custo * 100.0) if custo > 0 else 0.0

        precos_atuais.append(round(p_atual, 4))
        vars_dia.append(round(var_d, 2))
        valores_moeda.append(round(val_m, 2))
        valores_brl.append(round(val_m * fator_fx, 2))
        custos_brl.append(round(custo * fator_fx, 2))
        pls_moeda.append(round(pl_m, 2))
        pls_pct.append(round(pl_p, 2))

    abertas["preco_atual"] = precos_atuais
    abertas["variacao_dia_pct"] = vars_dia
    abertas["valor_mercado"] = valores_moeda
    abertas["pl_aberto"] = pls_moeda
    abertas["pl_aberto_pct"] = pls_pct
    abertas["valor_brl"] = valores_brl
    abertas["custo_brl"] = custos_brl
    abertas["pl_aberto_brl"] = (abertas["valor_brl"] - abertas["custo_brl"]).round(2)

    total_brl = float(abertas["valor_brl"].sum())
    abertas["alocacao_pct"] = (
        (abertas["valor_brl"] / total_brl * 100.0).round(2) if total_brl > 0 else 0.0
    )
    abertas = abertas.sort_values("valor_brl", ascending=False).reset_index(drop=True)

    custo_total_brl = float(abertas["custo_brl"].sum())
    pl_aberto_brl = total_brl - custo_total_brl
    resumo = {
        "patrimonio_brl": round(total_brl, 2),
        "custo_brl": round(custo_total_brl, 2),
        "pl_aberto_brl": round(pl_aberto_brl, 2),
        "pl_aberto_pct": round((pl_aberto_brl / custo_total_brl * 100.0) if custo_total_brl > 0 else 0.0, 2),
        "pl_realizado_total": round(float(pos["pl_realizado"].sum()), 2),
        "proventos_total": round(float(pos["proventos"].sum()), 2),
        "usd_brl": round(usd_brl, 4),
    }
    return abertas, resumo


GRUPO_ALOCACAO_MAP = {
    "acao_us": "Ações/ETFs EUA",
    "etf_us": "Ações/ETFs EUA",
    "renda_fixa": "Renda Fixa (BRL)",
    "cripto": "Cripto (BTC)",
    "acao_br": "Ações/FIIs B3",
    "fii": "Ações/FIIs B3",
}


def calcular_rebalanceamento(
    df_carteira: pd.DataFrame,
    metas_pct: dict[str, float],
    valor_novo_aporte_brl: float = 0.0,
) -> pd.DataFrame:
    """Calcula quanto aportar em cada macro-classe para aproximar a carteira das metas (%)
    sem precisar vender posições (rebalanceamento por novos aportes).
    """
    classes = list(metas_pct.keys())
    atual_por_classe: dict[str, float] = {c: 0.0 for c in classes}

    if df_carteira is not None and not df_carteira.empty:
        for _, r in df_carteira.iterrows():
            grp = GRUPO_ALOCACAO_MAP.get(str(r.get("classe", "")), "Ações/ETFs EUA")
            atual_por_classe[grp] = atual_por_classe.get(grp, 0.0) + float(r.get("valor_brl", 0.0) or 0.0)

    patrimonio_atual = sum(atual_por_classe.values())
    aporte = max(0.0, float(valor_novo_aporte_brl or 0.0))
    patrimonio_final = patrimonio_atual + aporte

    soma_metas = sum(max(0.0, float(v)) for v in metas_pct.values())
    metas_norm = (
        {k: (max(0.0, float(v)) / soma_metas * 100.0) for k, v in metas_pct.items()}
        if soma_metas > 0
        else {k: 0.0 for k in classes}
    )

    # Déficit positivo = quanto falta para atingir o valor-alvo após o aporte
    deficits: dict[str, float] = {}
    for c in classes:
        alvo_brl = patrimonio_final * (metas_norm.get(c, 0.0) / 100.0)
        deficits[c] = max(0.0, alvo_brl - atual_por_classe.get(c, 0.0))

    soma_deficits = sum(deficits.values())
    aportes_rec: dict[str, float] = {}
    for c in classes:
        if aporte <= 0:
            aportes_rec[c] = 0.0
        elif soma_deficits > 0:
            aportes_rec[c] = round(aporte * (deficits[c] / soma_deficits), 2)
        else:
            aportes_rec[c] = round(aporte * (metas_norm.get(c, 0.0) / 100.0), 2)

    # Ajuste de centavos de arredondamento na classe de maior aporte
    if aporte > 0 and aportes_rec:
        diff_centavos = round(aporte - sum(aportes_rec.values()), 2)
        maior_c = max(aportes_rec, key=lambda k: aportes_rec[k])
        aportes_rec[maior_c] = round(aportes_rec[maior_c] + diff_centavos, 2)

    linhas = []
    for c in classes:
        val_atual = round(atual_por_classe.get(c, 0.0), 2)
        pct_atual = round((val_atual / patrimonio_atual * 100.0) if patrimonio_atual > 0 else 0.0, 2)
        meta_c = round(metas_norm.get(c, 0.0), 2)
        ap_c = aportes_rec.get(c, 0.0)
        val_pos = round(val_atual + ap_c, 2)
        pct_pos = round((val_pos / patrimonio_final * 100.0) if patrimonio_final > 0 else 0.0, 2)

        if ap_c > 0.01:
            acao = f"🟢 Aportar R$ {ap_c:,.2f}"
        elif pct_atual < meta_c - 0.5:
            acao = f"🟡 Abaixo da meta ({pct_atual - meta_c:+.1f}%)"
        elif pct_atual > meta_c + 0.5:
            acao = f"⏸️ Acima da meta ({pct_atual - meta_c:+.1f}%)"
        else:
            acao = "✅ Na meta"

        linhas.append(
            {
                "classe": c,
                "valor_atual_brl": val_atual,
                "pct_atual": pct_atual,
                "pct_meta": meta_c,
                "desvio_pct": round(pct_atual - meta_c, 2),
                "aporte_recomendado_brl": ap_c,
                "valor_pos_aporte_brl": val_pos,
                "pct_pos_aporte": pct_pos,
                "acao": acao,
            }
        )

    return pd.DataFrame(linhas)


def calcular_evolucao_aportes_mensal(
    df_operacoes: pd.DataFrame,
    patrimonio_atual_brl: float = 0.0,
    usd_brl: float = 5.80,
    df_cotacoes: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Calcula a curva mensal de aportes líquidos e capital acumulado em BRL,
    combinando com snapshots reais de patrimônio gravados na aba `cotacoes`.
    """
    if df_operacoes is None or df_operacoes.empty:
        return pd.DataFrame(columns=["ano_mes", "aporte_liquido_brl", "capital_acumulado_brl", "patrimonio_mercado_brl"])

    ops = df_operacoes.copy()
    ops["data_dt"] = ops["data"].apply(parse_data)
    ops = ops.dropna(subset=["data_dt"]).sort_values("data_dt")
    if ops.empty:
        return pd.DataFrame(columns=["ano_mes", "aporte_liquido_brl", "capital_acumulado_brl", "patrimonio_mercado_brl"])

    ops["ano_mes"] = ops["data_dt"].apply(lambda d: d.strftime("%Y-%m"))

    fluxos = []
    for _, op in ops.iterrows():
        tipo = str(op.get("tipo", "compra")).lower()
        if tipo not in ("compra", "venda", "aporte", "resgate"):
            continue
        vt = parse_numero(op.get("valor_total"))
        if vt is None:
            q = abs(parse_numero(op.get("quantidade")) or 0.0)
            p = abs(parse_numero(op.get("preco")) or 0.0)
            vt = q * p
        moeda = str(op.get("moeda", "USD")).upper()
        val_brl = abs(vt) * (usd_brl if moeda == "USD" else 1.0)
        sinal = 1.0 if tipo in ("compra", "aporte") else -1.0
        fluxos.append({"ano_mes": op["ano_mes"], "fluxo_brl": sinal * val_brl})

    if not fluxos:
        return pd.DataFrame(columns=["ano_mes", "aporte_liquido_brl", "capital_acumulado_brl", "patrimonio_mercado_brl"])

    df_m = (
        pd.DataFrame(fluxos)
        .groupby("ano_mes", as_index=False)["fluxo_brl"]
        .sum()
        .rename(columns={"fluxo_brl": "aporte_liquido_brl"})
        .sort_values("ano_mes")
        .reset_index(drop=True)
    )
    df_m["aporte_liquido_brl"] = df_m["aporte_liquido_brl"].round(2)
    df_m["capital_acumulado_brl"] = df_m["aporte_liquido_brl"].cumsum().round(2)

    # Lê snapshots reais de patrimônio da aba `cotacoes` (codigo == 'SNAPSHOT_PATRIMONIO_BRL')
    snapshots: dict[str, float] = {}
    if df_cotacoes is not None and not df_cotacoes.empty:
        snaps = df_cotacoes[df_cotacoes["codigo"] == "SNAPSHOT_PATRIMONIO_BRL"].copy()
        for _, s in snaps.iterrows():
            d_s = parse_data(s.get("data"))
            v_s = parse_numero(s.get("valor"))
            if d_s and v_s is not None:
                snapshots[d_s.strftime("%Y-%m")] = round(float(v_s), 2)

    mes_atual = date.today().strftime("%Y-%m")
    if patrimonio_atual_brl > 0:
        snapshots[mes_atual] = round(float(patrimonio_atual_brl), 2)
        if mes_atual not in df_m["ano_mes"].values:
            ult_cap = float(df_m["capital_acumulado_brl"].iloc[-1]) if not df_m.empty else 0.0
            df_m = pd.concat(
                [
                    df_m,
                    pd.DataFrame(
                        [
                            {
                                "ano_mes": mes_atual,
                                "aporte_liquido_brl": 0.0,
                                "capital_acumulado_brl": ult_cap,
                            }
                        ]
                    ),
                ],
                ignore_index=True,
            )

    df_m["patrimonio_mercado_brl"] = df_m["ano_mes"].map(lambda m: snapshots.get(m))
    return df_m
