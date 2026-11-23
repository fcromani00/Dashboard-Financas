"""Central de Investimentos V2 — Patrimônio consolidado em BRL e USD:
- Ações e ETFs EUA (Inter US)
- Renda Fixa BRL (Meu Porquinho Inter e CDB Mercado Pago)
- Cripto (Bitcoin na Binance)
- Lançamento de operações, ajuste rápido de saldo de Renda Fixa e importação de notas Inter US.
"""

from __future__ import annotations

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from core.portfolio import (
    buscar_cotacoes_atuais,
    buscar_selic_atual,
    calcular_evolucao_aportes_mensal,
    calcular_ir_iof_renda_fixa,
    calcular_rebalanceamento,
    consolidar_carteira,
    exportar_yahoo_financas,
    projetar_rendimento_rf,
)
from core.state import invalidar_abas, ler_aba, mapa_config, obter_repo, salvar_config
from core.theme import badge_instituicao_html, estilizar_altair
from core.utils import agora_iso, id_deterministico, novo_id, parse_data, parse_numero
from functions import tratar_nota_corretagem_us_inter


@st.cache_data(ttl=1800, show_spinner=False)
def _cotacoes_cacheadas(codigos: tuple[str, ...]) -> dict[str, tuple[float, float]]:
    return buscar_cotacoes_atuais(list(codigos))


@st.cache_data(ttl=3600, show_spinner=False)
def _selic_cacheada() -> tuple[float, float, str]:
    return buscar_selic_atual()


col_h1, col_h2 = st.columns([5, 1])
with col_h1:
    st.title("Carteira de Investimentos")
    st.caption("Inter US · Porquinho Inter · Cofrinhos & CDB Mercado Pago · Cripto")
with col_h2:
    if st.button("Atualizar Preços", icon=":material/refresh:", use_container_width=True):
        _cotacoes_cacheadas.clear()
        invalidar_abas("ativos", "operacoes", "renda_fixa")
        st.rerun()

try:
    df_ativos = ler_aba("ativos")
    df_ops = ler_aba("operacoes")
    df_rf = ler_aba("renda_fixa")
    df_cotacoes = ler_aba("cotacoes")
    cfg = mapa_config()
except Exception as exc:
    st.error(f"Erro ao carregar abas de investimentos: {exc}")
    st.stop()

codigos_yf = tuple(
    sorted(
        {
            str(c).strip()
            for c in df_ativos[df_ativos["fonte_cotacao"] == "yfinance"]["codigo_cotacao"].tolist()
            if c
        }
        | {"USDBRL=X", "BTC-BRL"}
    )
)

with st.spinner("Atualizando cotações em lote (Yahoo Finance)..."):
    mapa_precos = _cotacoes_cacheadas(codigos_yf)
    selic_aa, cdi_aa, _ = _selic_cacheada()
    df_carteira, resumo = consolidar_carteira(df_ativos, df_ops, precos_yf=mapa_precos)

usd_brl = resumo["usd_brl"]

# ==================== KPIs CONSOLIDADOS EM BRL ====================
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Patrimônio Total", f"R$ {resumo['patrimonio_brl']:,.2f}")
k2.metric("Custo Investido", f"R$ {resumo['custo_brl']:,.2f}")
k3.metric(
    "P&L Aberto",
    f"R$ {resumo['pl_aberto_brl']:,.2f}",
    delta=f"{resumo.get('pl_aberto_pct', 0.0):.2f}%",
)
k4.metric("Realizado + Proventos", f"R$ {resumo.get('pl_realizado_total', 0.0) + resumo.get('proventos_total', 0.0):,.2f}")
k5.metric("USD / BRL", f"R$ {usd_brl:.4f}")
k6.metric("Selic (a.a.)", f"{selic_aa:.2f}%", delta=f"CDI {cdi_aa:.2f}%", delta_color="off")

st.markdown("---")

tab_visao, tab_evol_aporte, tab_us, tab_rf_cripto, tab_lancar = st.tabs(
    [
        "Alocação",
        "Evolução & Aporte",
        "EUA (Inter US)",
        "Renda Fixa & Cripto",
        "Lançar / Nota PDF",
    ]
)

MAPA_CLASSE_NOME = {
    "acao_us": "Ações EUA",
    "etf_us": "ETFs EUA",
    "renda_fixa": "Renda Fixa (BRL)",
    "cripto": "Cripto (BTC)",
    "acao_br": "Ações B3",
    "fii": "FIIs B3",
}

# ==============================================================================
# ABA 1: ALOCAÇÃO & VISÃO GERAL
# ==============================================================================
with tab_visao:
    if df_carteira.empty:
        st.info("Nenhuma posição aberta encontrada.")
    else:
        df_carteira["Classe_Label"] = df_carteira["classe"].map(lambda c: MAPA_CLASSE_NOME.get(c, c))

        c_a1, c_a2 = st.columns([2, 3])
        with c_a1:
            por_classe = (
                df_carteira.groupby("Classe_Label", as_index=False)["valor_brl"]
                .sum()
                .sort_values("valor_brl", ascending=False)
            )
            por_classe["pct"] = (por_classe["valor_brl"] / resumo["patrimonio_brl"] * 100.0).round(1)

            chart_donut = (
                alt.Chart(por_classe)
                .mark_arc(innerRadius=55, cornerRadius=4)
                .encode(
                    theta=alt.Theta("valor_brl:Q"),
                    color=alt.Color("Classe_Label:N", title="Classe"),
                    tooltip=[
                        alt.Tooltip("Classe_Label:N", title="Classe"),
                        alt.Tooltip("valor_brl:Q", title="Valor (R$)", format=",.2f"),
                        alt.Tooltip("pct:Q", title="% da Carteira", format=".1f"),
                    ],
                )
                .properties(height=280, title="Distribuição por Classe (R$)")
            )
            st.altair_chart(chart_donut, use_container_width=True)
            st.dataframe(
                por_classe,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Classe_Label": "Classe",
                    "valor_brl": st.column_config.NumberColumn("Valor (R$)", format="R$ %.2f"),
                    "pct": st.column_config.NumberColumn("Peso", format="%.1f%%"),
                },
            )

        with c_a2:
            top15 = df_carteira.head(15).copy()
            chart_top = (
                alt.Chart(top15)
                .mark_bar(cornerRadiusEnd=4, color="#2E8B57")
                .encode(
                    x=alt.X("valor_brl:Q", title="Valor em R$"),
                    y=alt.Y("ticker:N", sort="-x", title="Ativo"),
                    tooltip=[
                        "ticker:N",
                        "nome:N",
                        alt.Tooltip("valor_brl:Q", title="Valor (R$)", format=",.2f"),
                        alt.Tooltip("alocacao_pct:Q", title="% Carteira", format=".2f"),
                        alt.Tooltip("pl_aberto_pct:Q", title="P&L %", format=".2f"),
                    ],
                )
                .properties(height=380, title="Maiores Posições da Carteira (em R$)")
            )
            st.altair_chart(chart_top, use_container_width=True)

# ==============================================================================
# ABA 2: EVOLUÇÃO PATRIMONIAL & CALCULADORA DE PRÓXIMO APORTE
# ==============================================================================
with tab_evol_aporte:
    st.subheader("🎯 Calculadora de Próximo Aporte & Rebalanceamento")
    st.caption(
        "Defina suas metas de alocação por classe e simule onde colocar seu próximo aporte sem precisar vender ativos."
    )

    meta_us_padrao = float(cfg.get("alocacao.meta_us", "60") or 60.0)
    meta_rf_padrao = float(cfg.get("alocacao.meta_rf", "30") or 30.0)
    meta_btc_padrao = float(cfg.get("alocacao.meta_btc", "10") or 10.0)
    meta_b3_padrao = float(cfg.get("alocacao.meta_b3", "0") or 0.0)

    c_m1, c_m2, c_m3, c_m4, c_m5 = st.columns([1.1, 1.1, 1.1, 1.1, 1.6])
    with c_m1:
        m_us = st.number_input("🇺🇸 Meta EUA (%)", min_value=0.0, max_value=100.0, value=meta_us_padrao, step=5.0)
    with c_m2:
        m_rf = st.number_input("🐷 Meta Renda Fixa (%)", min_value=0.0, max_value=100.0, value=meta_rf_padrao, step=5.0)
    with c_m3:
        m_btc = st.number_input("₿ Meta Bitcoin (%)", min_value=0.0, max_value=100.0, value=meta_btc_padrao, step=5.0)
    with c_m4:
        m_b3 = st.number_input("🇧🇷 Meta B3 (%)", min_value=0.0, max_value=100.0, value=meta_b3_padrao, step=5.0)
    with c_m5:
        novo_aporte_brl = st.number_input(
            "💰 Valor do Novo Aporte (R$)",
            min_value=0.0,
            value=1000.0,
            step=200.0,
            format="%.2f",
        )

    metas_dict = {
        "Ações/ETFs EUA": m_us,
        "Renda Fixa (BRL)": m_rf,
        "Cripto (BTC)": m_btc,
        "Ações/FIIs B3": m_b3,
    }

    if st.button("💾 Salvar Metas de Alocação na Planilha"):
        salvar_config(
            {
                "alocacao.meta_us": str(m_us),
                "alocacao.meta_rf": str(m_rf),
                "alocacao.meta_btc": str(m_btc),
                "alocacao.meta_b3": str(m_b3),
            }
        )
        st.toast("✅ Metas de alocação salvas!")

    df_reb = calcular_rebalanceamento(df_carteira, metas_dict, valor_novo_aporte_brl=novo_aporte_brl)
    st.dataframe(
        df_reb,
        hide_index=True,
        use_container_width=True,
        column_config={
            "classe": "Classe de Ativo",
            "valor_atual_brl": st.column_config.NumberColumn("Valor Atual", format="R$ %.2f"),
            "pct_atual": st.column_config.NumberColumn("% Atual", format="%.1f%%"),
            "pct_meta": st.column_config.NumberColumn("% Meta", format="%.1f%%"),
            "desvio_pct": st.column_config.NumberColumn("Desvio", format="%+.1f%%"),
            "aporte_recomendado_brl": st.column_config.NumberColumn("Aporte Sugerido (R$)", format="R$ %.2f"),
            "valor_pos_aporte_brl": st.column_config.NumberColumn("Valor Pós-Aporte", format="R$ %.2f"),
            "pct_pos_aporte": st.column_config.NumberColumn("% Pós-Aporte", format="%.1f%%"),
            "acao": "Recomendação",
        },
    )

    ap_us_brl = float(
        df_reb[df_reb["classe"] == "Ações/ETFs EUA"]["aporte_recomendado_brl"].iloc[0]
    ) if not df_reb.empty else 0.0
    if ap_us_brl > 0 and usd_brl > 0:
        st.info(
            f"🇺🇸 **Fatia para Inter US:** R$ {ap_us_brl:,.2f} equivale a aproximadamente **US$ {ap_us_brl / usd_brl:,.2f}** (câmbio R$ {usd_brl:.4f})."
        )

    st.markdown("---")
    col_ev1, col_ev2 = st.columns([4, 1.4])
    with col_ev1:
        st.subheader("Evolução de Aportes & Patrimônio Acumulado (BRL)")
    with col_ev2:
        if st.button("Salvar Snapshot", icon=":material/photo_camera:", use_container_width=True):
            obter_repo().append(
                "cotacoes",
                [
                    {
                        "data": date.today(),
                        "codigo": "SNAPSHOT_PATRIMONIO_BRL",
                        "valor": resumo["patrimonio_brl"],
                        "moeda": "BRL",
                    }
                ],
            )
            invalidar_abas("cotacoes")
            st.toast("✅ Snapshot patrimonial registrado na aba `cotacoes`!")
            st.rerun()

    df_evol = calcular_evolucao_aportes_mensal(
        df_ops,
        patrimonio_atual_brl=resumo["patrimonio_brl"],
        usd_brl=usd_brl,
        df_cotacoes=df_cotacoes,
    )
    if df_evol.empty:
        st.info("Ainda não há histórico de operações para plotar a evolução mensal.")
    else:
        ev_c1, ev_c2 = st.columns(2)
        with ev_c1:
            chart_cap = (
                alt.Chart(df_evol)
                .mark_area(line={"color": "#1B5E20", "strokeWidth": 3}, color="#81C784", opacity=0.45)
                .encode(
                    x=alt.X("ano_mes:N", title="Ano/Mês"),
                    y=alt.Y("capital_acumulado_brl:Q", title="R$ Acumulado"),
                    tooltip=[
                        alt.Tooltip("ano_mes:N", title="Mês"),
                        alt.Tooltip("capital_acumulado_brl:Q", title="Capital Aportado Acum. (R$)", format=",.2f"),
                    ],
                )
                .properties(height=300, title="Capital Investido Acumulado (R$)")
            )
            st.altair_chart(estilizar_altair(chart_cap), use_container_width=True, theme=None)

        with ev_c2:
            chart_ap = (
                alt.Chart(df_evol)
                .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3, color="#FF7A00")
                .encode(
                    x=alt.X("ano_mes:N", title="Ano/Mês"),
                    y=alt.Y("aporte_liquido_brl:Q", title="Aporte Líquido (R$)"),
                    tooltip=[
                        alt.Tooltip("ano_mes:N", title="Mês"),
                        alt.Tooltip("aporte_liquido_brl:Q", title="Aporte Líquido (R$)", format=",.2f"),
                    ],
                )
                .properties(height=300, title="Aportes Líquidos Mensais (R$)")
            )
            st.altair_chart(estilizar_altair(chart_ap), use_container_width=True, theme=None)

# ==============================================================================
# ABA 3: AÇÕES & ETFS (INTER US)
# ==============================================================================
with tab_us:
    df_us = (
        df_carteira[df_carteira["classe"].isin(["acao_us", "etf_us"])].copy()
        if not df_carteira.empty
        else pd.DataFrame()
    )
    if df_us.empty:
        st.info("Nenhuma posição em Ações/ETFs EUA aberta.")
    else:
        val_us_usd = float(df_us["valor_mercado"].sum())
        custo_us_usd = float(df_us["custo_total"].sum())
        pl_us_usd = val_us_usd - custo_us_usd
        pl_us_pct = (pl_us_usd / custo_us_usd * 100.0) if custo_us_usd > 0 else 0.0

        u1, u2, u3, u4 = st.columns(4)
        u1.metric("🇺🇸 Valor de Mercado (USD)", f"US$ {val_us_usd:,.2f}", f"R$ {val_us_usd * usd_brl:,.2f}")
        u2.metric("💵 Custo Investido (USD)", f"US$ {custo_us_usd:,.2f}")
        u3.metric("📈 P&L Aberto (USD)", f"US$ {pl_us_usd:,.2f}", f"{pl_us_pct:.2f}%")
        u4.metric("🎯 Ativos em Carteira", len(df_us))

        st.dataframe(
            df_us[
                [
                    "ticker",
                    "nome",
                    "quantidade",
                    "preco_medio",
                    "preco_atual",
                    "variacao_dia_pct",
                    "custo_total",
                    "valor_mercado",
                    "pl_aberto",
                    "pl_aberto_pct",
                    "valor_brl",
                    "alocacao_pct",
                ]
            ],
            hide_index=True,
            use_container_width=True,
            column_config={
                "ticker": "Ticker",
                "nome": "Empresa / ETF",
                "quantidade": st.column_config.NumberColumn("Qtd", format="%.4f"),
                "preco_medio": st.column_config.NumberColumn("PM (US$)", format="$ %.2f"),
                "preco_atual": st.column_config.NumberColumn("Cotação (US$)", format="$ %.2f"),
                "variacao_dia_pct": st.column_config.NumberColumn("Dia %", format="%.2f%%"),
                "custo_total": st.column_config.NumberColumn("Custo (US$)", format="$ %.2f"),
                "valor_mercado": st.column_config.NumberColumn("Valor (US$)", format="$ %.2f"),
                "pl_aberto": st.column_config.NumberColumn("P&L (US$)", format="$ %.2f"),
                "pl_aberto_pct": st.column_config.NumberColumn("P&L %", format="%.2f%%"),
                "valor_brl": st.column_config.NumberColumn("Valor (R$)", format="R$ %.2f"),
                "alocacao_pct": st.column_config.NumberColumn("% Carteira", format="%.2f%%"),
            },
        )

    with st.expander("Exportar Carteira para Yahoo Finanças (CSV)", icon=":material/ios_share:", expanded=False):
        st.caption(
            "Gera o arquivo `.csv` no formato oficial do Yahoo Finance (`Symbol, Trade Date, Purchase Price, Quantity`)."
        )
        cy1, cy2, cy3 = st.columns([2.2, 1.4, 1.4])
        with cy1:
            modo_yf = st.radio(
                "Formato de exportação",
                options=["lotes_fifo", "abertas"],
                format_func=lambda x: {
                    "lotes_fifo": "Lotes de compra em carteira — datas e preços reais (Recomendado)",
                    "abertas": "Consolidado — 1 linha por ativo com preço médio",
                }[x],
                horizontal=False,
                key="yf_export_modo",
            )
            st.caption(
                "ℹ️ O CSV do Yahoo só aceita **compras** (não tem coluna de venda). Vendas são abatidas dos lotes "
                "mais antigos (FIFO, mesmo critério do app Inter), então Qtd e Custo batem com a corretora. "
                "Antes de importar, **apague o portfólio importado anteriormente** no Yahoo para não duplicar."
            )
        with cy2:
            incluir_cripto_yf = st.checkbox("Incluir Cripto (BTC/ETH/SOL-USD)", value=False, key="yf_incluir_cripto")
        df_yf_exp, csv_yf_bytes = exportar_yahoo_financas(
            df_ativos,
            df_ops,
            modo=modo_yf,
            incluir_cripto=incluir_cripto_yf,
            usd_brl=usd_brl,
        )
        with cy3:
            st.download_button(
                label=f"Baixar CSV Yahoo ({len(df_yf_exp)} linhas)",
                icon=":material/download:",
                data=csv_yf_bytes,
                file_name=f"carteira_yahoo_{date.today().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                type="primary",
                use_container_width=True,
                disabled=df_yf_exp.empty,
            )

# ==============================================================================
# ABA 3: RENDA FIXA (PORQUINHO INTER / CDB MP) & BITCOIN (BINANCE)
# ==============================================================================
with tab_rf_cripto:
    c_rf, c_btc = st.columns(2)

    with c_rf:
        st.subheader("🐷 Renda Fixa (Porquinho Inter & CDB Mercado Pago)")
        st.caption(
            "Registre aportes/resgates ou atualize o saldo líquido direto com o valor exibido no app do banco."
        )

        ativos_rf = df_ativos[df_ativos["classe"] == "renda_fixa"].copy()
        for _, at in ativos_rf.iterrows():
            at_id = str(at["id"])
            ticker = str(at["ticker"])
            nome = str(at["nome"])
            conta = str(at["conta"])
            linha_pos = (
                df_carteira[df_carteira["ativo_id"] == at_id].iloc[0]
                if not df_carteira.empty and (df_carteira["ativo_id"] == at_id).any()
                else None
            )
            saldo_atual = float(linha_pos["valor_brl"]) if linha_pos is not None else 0.0
            custo_atual = float(linha_pos["custo_brl"]) if linha_pos is not None else 0.0
            rend_acum = saldo_atual - custo_atual

            with st.container(border=True):
                st.markdown(f"#### {nome} &nbsp; {badge_instituicao_html(conta)}", unsafe_allow_html=True)
                m_a, m_b, m_c = st.columns(3)
                m_a.metric("Saldo Atual", f"R$ {saldo_atual:,.2f}")
                m_b.metric("Total Aportado", f"R$ {custo_atual:,.2f}")
                m_c.metric("Rendimento", f"R$ {rend_acum:,.2f}")

                info_rf = df_rf[df_rf["ativo_id"] == at_id].iloc[0] if not df_rf.empty and (df_rf["ativo_id"] == at_id).any() else None
                if info_rf is not None:
                    taxa_cdi = parse_numero(info_rf.get("taxa_pct")) or 100.0
                    dt_ap = parse_data(info_rf.get("data_aplicacao"))
                    dt_venc = parse_data(info_rf.get("vencimento"))
                    trib = calcular_ir_iof_renda_fixa(dt_ap, rendimento_bruto=max(0.0, rend_acum))
                    proj = projetar_rendimento_rf(saldo_atual, taxa_cdi, cdi_aa)
                    partes_meta = [
                        f"**{taxa_cdi:.0f}% do CDI** ({proj['taxa_efetiva_aa']:.2f}% a.a.)",
                        f"~R$ {proj['rendimento_mensal_bruto']:,.2f}/mês bruto",
                    ]
                    if dt_ap:
                        partes_meta.append(f"Aplicado em {dt_ap.strftime('%d/%m/%Y')} ({trib['dias_corridos']}d)")
                    if dt_venc:
                        partes_meta.append(f"Vence em {dt_venc.strftime('%d/%m/%Y')}")
                    partes_meta.append(f"IOF: **{trib['aliquota_iof_pct']:.0f}%** · IR: **{trib['aliquota_ir_pct']:.1f}%**")
                    st.caption(" · ".join(partes_meta))
                    if trib["aliquota_iof_pct"] > 0 and trib["data_isencao_iof"]:
                        st.warning(
                            f"⚠️ Em janela de **IOF regressivo ({trib['aliquota_iof_pct']:.0f}%)** — isenção total de IOF em **{trib['data_isencao_iof'].strftime('%d/%m/%Y')}** (faltam {trib['dias_para_isencao_iof']} dias)."
                        )

                with st.expander("Atualizar saldo / registrar movimentação", icon=":material/edit_note:", expanded=False):
                    with st.form(f"form_rf_{at_id}", clear_on_submit=True):
                        f1, f2, f3 = st.columns([1.4, 1.3, 1.3])
                        with f1:
                            acao_rf = st.selectbox(
                                "Ação",
                                options=["aporte", "resgate", "ajuste_saldo"],
                                format_func=lambda x: {
                                    "aporte": "➕ Novo Aporte",
                                    "resgate": "➖ Resgate",
                                    "ajuste_saldo": "🎯 Cravar Saldo Atual do App",
                                }[x],
                                key=f"acao_{at_id}",
                            )
                        with f2:
                            val_rf = st.number_input("Valor (R$)", min_value=0.0, step=50.0, format="%.2f", key=f"val_{at_id}")
                        with f3:
                            dt_rf = st.date_input("Data", value=date.today(), format="DD/MM/YYYY", key=f"dt_{at_id}")

                        if st.form_submit_button("Salvar", use_container_width=True):
                            if val_rf > 0:
                                obter_repo().append(
                                    "operacoes",
                                    [
                                        {
                                            "id": novo_id(),
                                            "data": dt_rf,
                                            "ativo_id": at_id,
                                            "conta": conta,
                                            "tipo": acao_rf,
                                            "quantidade": 1.0,
                                            "preco": round(val_rf, 2),
                                            "taxas": 0.0,
                                            "valor_total": round(val_rf, 2),
                                            "moeda": "BRL",
                                            "importacao_id": "",
                                            "observacao": f"{acao_rf} via painel Renda Fixa",
                                            "criado_em": agora_iso(),
                                        }
                                    ],
                                )
                                invalidar_abas("operacoes")
                                st.toast(f"✅ {nome} atualizado!")
                                st.rerun()

    with c_btc:
        st.subheader("Cripto")
        st.markdown(
            f"{badge_instituicao_html('Binance')} &nbsp; {badge_instituicao_html('Inter Cripto')}",
            unsafe_allow_html=True,
        )
        preco_btc_brl, var_btc = mapa_precos.get("BTC-BRL", (0.0, 0.0))
        st.metric("Cotação Bitcoin (BTC-BRL)", f"R$ {preco_btc_brl:,.2f}", f"{var_btc:.2f}% (dia)")

        df_cripto = df_carteira[df_carteira["classe"] == "cripto"].copy() if not df_carteira.empty else pd.DataFrame()
        if not df_cripto.empty:
            st.dataframe(
                df_cripto[["ticker", "conta", "quantidade", "preco_medio", "valor_brl", "pl_aberto_pct"]],
                hide_index=True,
                use_container_width=True,
                column_config={
                    "ticker": "Ativo",
                    "conta": "Corretora",
                    "quantidade": st.column_config.NumberColumn("Qtd", format="%.6f"),
                    "preco_medio": st.column_config.NumberColumn("PM (R$)", format="R$ %.2f"),
                    "valor_brl": st.column_config.NumberColumn("Valor (R$)", format="R$ %.2f"),
                    "pl_aberto_pct": st.column_config.NumberColumn("P&L %", format="%.2f%%"),
                },
            )

        at_btc = df_ativos[df_ativos["ticker"] == "BTC"]
        if not at_btc.empty:
            btc_id = str(at_btc.iloc[0]["id"])
            with st.expander("Registrar compra ou venda de BTC (Binance)", expanded=False):
                with st.form("form_btc", clear_on_submit=True):
                    c_b1, c_b2, c_b3 = st.columns(3)
                    with c_b1:
                        tipo_btc = st.selectbox("Tipo", options=["compra", "venda"])
                    with c_b2:
                        valor_aporte_brl = st.number_input("Valor total em R$", min_value=0.0, step=100.0, format="%.2f")
                    with c_b3:
                        qtd_btc_in = st.number_input(
                            "Quantidade de BTC (ou 0 p/ calcular)",
                            min_value=0.0,
                            step=0.0001,
                            format="%.8f",
                        )
                    dt_btc = st.date_input("Data da operação", value=date.today(), format="DD/MM/YYYY")

                    if st.form_submit_button("Salvar operação BTC", type="primary", use_container_width=True):
                        if valor_aporte_brl > 0 or qtd_btc_in > 0:
                            q_final = qtd_btc_in if qtd_btc_in > 0 else (valor_aporte_brl / preco_btc_brl if preco_btc_brl > 0 else 0.0)
                            p_final = (valor_aporte_brl / q_final) if (valor_aporte_brl > 0 and q_final > 0) else preco_btc_brl
                            vt_final = valor_aporte_brl if valor_aporte_brl > 0 else (q_final * p_final)
                            obter_repo().append(
                                "operacoes",
                                [
                                    {
                                        "id": novo_id(),
                                        "data": dt_btc,
                                        "ativo_id": btc_id,
                                        "conta": "Binance",
                                        "tipo": tipo_btc,
                                        "quantidade": round(q_final, 8),
                                        "preco": round(p_final, 2),
                                        "taxas": 0.0,
                                        "valor_total": round(vt_final, 2),
                                        "moeda": "BRL",
                                        "importacao_id": "",
                                        "observacao": "Binance BTC",
                                        "criado_em": agora_iso(),
                                    }
                                ],
                            )
                            invalidar_abas("operacoes")
                            st.success("✅ Operação de BTC registrada!")
                            st.rerun()

# ==============================================================================
# ABA 4: LANÇAR OPERAÇÃO MANUAL OU IMPORTAR NOTA DE CORRETAGEM INTER US
# ==============================================================================
with tab_lancar:
    col_l1, col_l2 = st.columns(2)

    with col_l1:
        st.subheader("📄 Importar Notas de Corretagem (Inter US PDF)")
        st.caption("Arraste um ou vários PDFs de confirmação (Trade Confirmation) da Inter US de uma vez.")
        pdfs_notas = st.file_uploader(
            "Selecione os PDFs de confirmação da Inter US",
            type=["pdf"],
            accept_multiple_files=True,
        )
        if pdfs_notas:
            dfs_extraidos = []
            for pdf_arq in pdfs_notas:
                df_n = tratar_nota_corretagem_us_inter(pdf_arq)
                if not df_n.empty:
                    df_n["Arquivo"] = pdf_arq.name
                    dfs_extraidos.append(df_n)

            if not dfs_extraidos:
                st.warning("Nenhuma operação reconhecida nos PDFs enviados.")
            else:
                df_nota = pd.concat(dfs_extraidos, ignore_index=True)
                st.dataframe(
                    df_nota[["Trade Date", "Symbol", "Security", "Action", "Price", "Quantity", "Arquivo"]],
                    hide_index=True,
                    use_container_width=True,
                )
                if st.button(f"💾 Gravar {len(df_nota)} operações na planilha V2", type="primary", use_container_width=True):
                    repo = obter_repo()
                    ativos_conhecidos = set(df_ativos["ticker"].str.upper().tolist())
                    # Assinaturas já existentes para evitar duplicar se subir o mesmo PDF duas vezes
                    chaves_existentes = set()
                    if not df_ops.empty:
                        for _, op_ex in df_ops.iterrows():
                            d_ex = parse_data(op_ex.get("data"))
                            q_ex = round(abs(parse_numero(op_ex.get("quantidade")) or 0.0), 6)
                            p_ex = round(abs(parse_numero(op_ex.get("preco")) or 0.0), 4)
                            chaves_existentes.add((str(d_ex), str(op_ex.get("ativo_id")), str(op_ex.get("tipo")), q_ex, p_ex))

                    novos_ativos = []
                    novas_ops = []
                    ignoradas_dup = 0

                    for _, r in df_nota.iterrows():
                        sym = str(r["Symbol"]).strip().upper()
                        at_id = id_deterministico("ativo", sym)
                        if sym not in ativos_conhecidos:
                            novos_ativos.append(
                                {
                                    "id": at_id,
                                    "ticker": sym,
                                    "nome": str(r.get("Security", sym)).strip(),
                                    "classe": "acao_us",
                                    "moeda": "USD",
                                    "conta": "Inter US",
                                    "fonte_cotacao": "yfinance",
                                    "codigo_cotacao": sym.replace(".", "-"),
                                    "ativo": "S",
                                }
                            )
                            ativos_conhecidos.add(sym)

                        d_op = parse_data(r["Trade Date"]) or date.today()
                        preco = abs(parse_numero(r["Price"]) or 0.0)
                        qtd = abs(parse_numero(r["Quantity"]) or 0.0)
                        acao = str(r.get("Action", "Buy")).lower()
                        tipo_op = "venda" if "sell" in acao else "compra"

                        assinatura = (str(d_op), at_id, tipo_op, round(qtd, 6), round(preco, 4))
                        if assinatura in chaves_existentes:
                            ignoradas_dup += 1
                            continue
                        chaves_existentes.add(assinatura)

                        novas_ops.append(
                            {
                                "id": novo_id(),
                                "data": d_op,
                                "ativo_id": at_id,
                                "conta": "Inter US",
                                "tipo": tipo_op,
                                "quantidade": round(qtd, 8),
                                "preco": round(preco, 6),
                                "taxas": 0.0,
                                "valor_total": round(qtd * preco, 2),
                                "moeda": "USD",
                                "importacao_id": str(r.get("Arquivo", "")),
                                "observacao": "Nota Inter US",
                                "criado_em": agora_iso(),
                            }
                        )

                    if novos_ativos:
                        repo.append("ativos", novos_ativos)
                    if novas_ops:
                        repo.append("operacoes", novas_ops)
                    invalidar_abas("ativos", "operacoes")
                    st.success(
                        f"✅ {len(novas_ops)} nova(s) operação(ões) gravada(s) ({ignoradas_dup} duplicata(s) ignorada(s))!"
                    )
                    st.rerun()

    with col_l2:
        st.subheader("✍️ Lançamento Manual (EUA, B3, Dividendos)")
        with st.form("form_op_manual", clear_on_submit=True):
            m1, m2, m3 = st.columns(3)
            with m1:
                ticker_m = st.text_input("Ticker", placeholder="Ex: AAPL, NVDA, PETR4...")
            with m2:
                classe_m = st.selectbox(
                    "Classe",
                    options=["acao_us", "etf_us", "acao_br", "fii", "cripto"],
                    format_func=lambda c: MAPA_CLASSE_NOME.get(c, c),
                )
            with m3:
                tipo_m = st.selectbox("Operação", options=["compra", "venda", "dividendo"])

            m4, m5, m6 = st.columns(3)
            with m4:
                qtd_m = st.number_input("Quantidade", min_value=0.0, step=1.0, format="%.6f")
            with m5:
                preco_m = st.number_input("Preço unitário / Valor provento", min_value=0.0, step=1.0, format="%.4f")
            with m6:
                dt_m = st.date_input("Data", value=date.today(), format="DD/MM/YYYY")

            if st.form_submit_button("💾 Registrar Operação", type="primary", use_container_width=True):
                sym = ticker_m.strip().upper()
                if sym and preco_m > 0:
                    repo = obter_repo()
                    moeda_m = "USD" if classe_m in ("acao_us", "etf_us") else "BRL"
                    conta_m = "Inter US" if moeda_m == "USD" else ("Binance" if classe_m == "cripto" else "Inter")
                    cod_yf = f"{sym}.SA" if classe_m in ("acao_br", "fii") and not sym.endswith(".SA") else sym.replace(".", "-")
                    at_id = id_deterministico("ativo", sym)

                    if sym not in set(df_ativos["ticker"].str.upper().tolist()):
                        repo.append(
                            "ativos",
                            [
                                {
                                    "id": at_id,
                                    "ticker": sym,
                                    "nome": sym,
                                    "classe": classe_m,
                                    "moeda": moeda_m,
                                    "conta": conta_m,
                                    "fonte_cotacao": "yfinance",
                                    "codigo_cotacao": cod_yf,
                                    "ativo": "S",
                                }
                            ],
                        )

                    q_eff = 1.0 if tipo_m == "dividendo" and qtd_m == 0 else qtd_m
                    repo.append(
                        "operacoes",
                        [
                            {
                                "id": novo_id(),
                                "data": dt_m,
                                "ativo_id": at_id,
                                "conta": conta_m,
                                "tipo": tipo_m,
                                "quantidade": round(q_eff, 8),
                                "preco": round(preco_m, 4),
                                "taxas": 0.0,
                                "valor_total": round(q_eff * preco_m, 2),
                                "moeda": moeda_m,
                                "importacao_id": "",
                                "observacao": "Manual V2",
                                "criado_em": agora_iso(),
                            }
                        ],
                    )
                    invalidar_abas("ativos", "operacoes")
                    st.success(f"✅ {tipo_m.title()} de {sym} registrada!")
                    st.rerun()
