"""Tela Hoje & Gastos (Finanças V2) — Mobile-first + Desktop Dashboard."""

from __future__ import annotations

import calendar
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from core.recurring import analisar_parcelas, detectar_recorrencias
from core.state import invalidar_abas, ler_aba, obter_repo
from core.transactions import TODAS_CATEGORIAS_V2
from core.utils import agora_iso

try:
    df_tx = ler_aba("transacoes")
    df_orc = ler_aba("orcamento")
    df_metas = ler_aba("metas")
    df_contas = ler_aba("contas")
except Exception as exc:
    st.error(f"Erro ao carregar dados da planilha V2: {exc}")
    st.stop()

if df_tx.empty:
    st.info("Nenhuma transação encontrada na aba `transacoes`.")
    st.stop()

# Preparação de datas e exclusão de transferências internas dos cálculos de receita/despesa
df_tx = df_tx.dropna(subset=["data", "valor"]).copy()
df_tx["ano_mes"] = df_tx["data"].apply(lambda d: d.strftime("%Y-%m"))
ult_data: date = df_tx["data"].max()
dias_sem_lancar = (date.today() - ult_data).days
qtd_revisar = int((df_tx["status"] == "revisar").sum())
qtd_provisorias = int((df_tx["status"] == "provisoria").sum())

banners = []
if dias_sem_lancar <= 3:
    banners.append(f"🟢 Último registro: **{ult_data.strftime('%d/%m/%Y')}** (em dia)")
elif dias_sem_lancar <= 10:
    banners.append(f"🟡 Último registro: **{ult_data.strftime('%d/%m/%Y')}** ({dias_sem_lancar} dias atrás)")
else:
    banners.append(f"🔴 Último registro: **{ult_data.strftime('%d/%m/%Y')}** ({dias_sem_lancar} dias sem atualizar)")
if qtd_revisar > 0:
    banners.append(f"📝 **{qtd_revisar}** aguardando categoria")
if qtd_provisorias > 0:
    banners.append(f"📱 **{qtd_provisorias}** do iPhone aguardando fatura")

# Cabeçalho compacto com seletor de mês e filtros em popover
meses_disp = sorted(df_tx["ano_mes"].unique().tolist(), reverse=True)
contas_disp = sorted([c for c in df_tx["conta"].unique().tolist() if c])

col_t1, col_m, col_pop, col_t2 = st.columns([3.4, 1.4, 1.3, 1.0])
with col_t1:
    st.title("Visão Geral & Orçamento")
with col_m:
    mes_selecionado = st.selectbox("Mês", options=meses_disp, index=0, label_visibility="collapsed")
with col_pop:
    with st.popover("Filtros", use_container_width=True):
        contas_sel = st.multiselect("Contas", options=contas_disp, default=contas_disp)
        incluir_transferencias = st.toggle("Mostrar transferências internas", value=False)
with col_t2:
    if st.button("Atualizar", use_container_width=True):
        invalidar_abas()
        st.rerun()

st.caption(" · ".join(banners + [f"{len(contas_sel)} conta(s) ativa(s)"]))

df_filtrado_contas = df_tx[df_tx["conta"].isin(contas_sel)] if contas_sel else df_tx.copy()
df_operacional = (
    df_filtrado_contas
    if incluir_transferencias
    else df_filtrado_contas[
        (df_filtrado_contas["transferencia"] != "S")
        & (df_filtrado_contas["categoria"] != "Transferência Interna")
    ]
)

df_mes = df_operacional[df_operacional["ano_mes"] == mes_selecionado].copy()

# Orçamento mensal (despesas)
orc_despesas = pd.DataFrame()
teto_orcamento_mes = 0.0
if not df_orc.empty:
    orc_mes = df_orc[(df_orc["mes"] == mes_selecionado) | (df_orc["mes"] == "padrao")].copy()
    orc_despesas = orc_mes[orc_mes["grupo"] != "Receita"].copy()
    teto_orcamento_mes = float(orc_despesas["valor"].sum())

receitas_mes = float(df_mes[df_mes["valor"] > 0]["valor"].sum())
despesas_mes = float(abs(df_mes[df_mes["valor"] < 0]["valor"].sum()))
saldo_mes = receitas_mes - despesas_mes
taxa_poupanca = ((saldo_mes / receitas_mes) * 100.0) if receitas_mes > 0 else 0.0

# Cálculo de quanto ainda pode gastar por dia no mês selecionado
ano_ref, mes_ref = [int(x) for x in mes_selecionado.split("-")]
dias_no_mes = calendar.monthrange(ano_ref, mes_ref)[1]
hoje = date.today()
if (ano_ref, mes_ref) == (hoje.year, hoje.month):
    dias_restantes = max(1, dias_no_mes - hoje.day + 1)
else:
    dias_restantes = dias_no_mes

restante_orcamento = teto_orcamento_mes - despesas_mes if teto_orcamento_mes > 0 else saldo_mes
disponivel_por_dia = restante_orcamento / dias_restantes

# ==================== KPIs DO MÊS ====================
k1, k2, k3, k4 = st.columns(4)
with k1:
    st.metric("Receitas", f"R$ {receitas_mes:,.2f}")
with k2:
    delta_orc = (
        f"R$ {teto_orcamento_mes - despesas_mes:,.2f} vs orçado"
        if teto_orcamento_mes > 0
        else None
    )
    st.metric(
        "Despesas",
        f"R$ {despesas_mes:,.2f}",
        delta=delta_orc,
        delta_color="normal" if (teto_orcamento_mes == 0 or despesas_mes <= teto_orcamento_mes) else "inverse",
    )
with k3:
    st.metric(
        "Saldo do Mês",
        f"R$ {saldo_mes:,.2f}",
        delta=f"{taxa_poupanca:.1f}% poupado" if receitas_mes > 0 else None,
    )
with k4:
    label_dia = "Restante / dia" if teto_orcamento_mes > 0 else "Saldo / dia"
    st.metric(label_dia, f"R$ {disponivel_por_dia:,.2f}")

st.markdown("---")

# ==================== ABAS PRINCIPAIS ====================
tab_mes, tab_evolucao, tab_recorrentes, tab_orc_metas, tab_extrato = st.tabs(
    [
        f"Gastos ({mes_selecionado})",
        "Histórico",
        "Fixos & Parcelas",
        "Orçamento & Metas",
        "Extrato",
    ]
)

with tab_mes:
    df_desp_mes = df_mes[df_mes["valor"] < 0].copy()
    df_desp_mes["gasto_abs"] = df_desp_mes["valor"].abs()

    if df_desp_mes.empty:
        st.info(f"Nenhuma despesa registrada em {mes_selecionado}.")
    else:
        c_g1, c_g2 = st.columns([3, 2])
        with c_g1:
            por_cat = (
                df_desp_mes.groupby("categoria", as_index=False)["gasto_abs"]
                .sum()
                .sort_values("gasto_abs", ascending=False)
            )
            por_cat["pct"] = (por_cat["gasto_abs"] / despesas_mes * 100.0).round(1)

            chart_cat = (
                alt.Chart(por_cat)
                .mark_bar(cornerRadiusEnd=6, color="#FF7A00")
                .encode(
                    x=alt.X("gasto_abs:Q", title="Gasto (R$)"),
                    y=alt.Y("categoria:N", sort="-x", title="Categoria"),
                    tooltip=[
                        alt.Tooltip("categoria:N", title="Categoria"),
                        alt.Tooltip("gasto_abs:Q", title="Gasto (R$)", format=",.2f"),
                        alt.Tooltip("pct:Q", title="% do Mês", format=".1f"),
                    ],
                )
                .properties(height=max(260, len(por_cat) * 28), title=f"Despesas por Categoria ({mes_selecionado})")
            )
            st.altair_chart(chart_cat, use_container_width=True)

        with c_g2:
            st.markdown("##### 🏆 Top 8 maiores gastos do mês")
            top_gastos = df_desp_mes.sort_values("gasto_abs", ascending=False)[
                ["data", "descricao", "categoria", "conta", "gasto_abs"]
            ].head(8)
            st.dataframe(
                top_gastos,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                    "descricao": "Descrição",
                    "categoria": "Categoria",
                    "conta": "Conta",
                    "gasto_abs": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
                },
            )

with tab_evolucao:
    st.subheader("Evolução Mensal: Receitas vs. Despesas")
    ultimos_n = st.slider("Quantidade de meses no gráfico", min_value=6, max_value=36, value=12, step=6)
    meses_recorte = sorted(df_operacional["ano_mes"].unique().tolist())[-ultimos_n:]
    df_rec = df_operacional[df_operacional["ano_mes"].isin(meses_recorte)].copy()

    rec_m = df_rec[df_rec["valor"] > 0].groupby("ano_mes")["valor"].sum()
    desp_m = df_rec[df_rec["valor"] < 0].groupby("ano_mes")["valor"].sum().abs()
    todos_m = sorted(set(rec_m.index) | set(desp_m.index))

    dados_hist = []
    for m in todos_m:
        r_val = float(rec_m.get(m, 0.0))
        d_val = float(desp_m.get(m, 0.0))
        dados_hist.append({"Ano/Mês": m, "Tipo": "Receitas", "Valor": round(r_val, 2)})
        dados_hist.append({"Ano/Mês": m, "Tipo": "Despesas", "Valor": round(d_val, 2)})

    df_hist_plot = pd.DataFrame(dados_hist)
    chart_hist = (
        alt.Chart(df_hist_plot)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("Ano/Mês:N", title="Ano/Mês"),
            xOffset="Tipo:N",
            y=alt.Y("Valor:Q", title="R$"),
            color=alt.Color(
                "Tipo:N",
                scale=alt.Scale(domain=["Receitas", "Despesas"], range=["#2E8B57", "#E5533D"]),
            ),
            tooltip=["Ano/Mês:N", "Tipo:N", alt.Tooltip("Valor:Q", format=",.2f")],
        )
        .properties(height=360)
    )
    st.altair_chart(chart_hist, use_container_width=True)

with tab_recorrentes:
    info_rec = detectar_recorrencias(df_operacional)
    info_parc = analisar_parcelas(df_operacional, mes_referencia=mes_selecionado)

    fixos_mes = info_rec["total_fixos_ativos_mes"]
    parc_mes = info_parc["total_mes"]
    parc_fut = info_parc["total_futuro"]
    comprometido_mes = fixos_mes + parc_mes
    pct_comp = (comprometido_mes / receitas_mes * 100.0) if receitas_mes > 0 else 0.0

    r1, r2, r3, r4 = st.columns(4)
    r1.metric(
        "🔒 Custos Fixos & Assinaturas Ativas",
        f"R$ {fixos_mes:,.2f}/mês",
        f"{info_rec['qtd_fixos_ativos']} identificados",
    )
    r2.metric(f"💳 Parcelas em {mes_selecionado}", f"R$ {parc_mes:,.2f}")
    r3.metric("🗓️ Parcelas Futuras (Total a Vencer)", f"R$ {parc_fut:,.2f}")
    r4.metric(
        "📌 Comprometimento (Fixos + Parcelas)",
        f"R$ {comprometido_mes:,.2f}",
        f"{pct_comp:.1f}% da receita do mês" if receitas_mes > 0 else None,
    )

    st.markdown("---")
    c_p1, c_p2 = st.columns([2, 3])
    with c_p1:
        st.markdown("##### 🗓️ Projeção de Parcelas nos Próximos Meses")
        df_proj = info_parc["projecao_futura"]
        if df_proj.empty:
            st.info("Nenhuma parcela futura pendente após este mês.")
        else:
            chart_proj = (
                alt.Chart(df_proj)
                .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, color="#FF7043")
                .encode(
                    x=alt.X("ano_mes:N", title="Mês Futuro"),
                    y=alt.Y("valor_comprometido:Q", title="R$ Comprometido"),
                    tooltip=[
                        alt.Tooltip("ano_mes:N", title="Mês"),
                        alt.Tooltip("valor_comprometido:Q", title="Total Parcelas (R$)", format=",.2f"),
                        alt.Tooltip("qtd_parcelas:Q", title="Qtd. Parcelas"),
                    ],
                )
                .properties(height=240)
            )
            st.altair_chart(chart_proj, use_container_width=True)

    with c_p2:
        st.markdown("##### 💳 Compras Parceladas em Andamento")
        df_at = info_parc["parcelas_ativas"]
        if df_at.empty:
            st.caption("Nenhuma compra parcelada com saldo restante identificada até este mês.")
        else:
            st.dataframe(
                df_at,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "descricao": "Compra / Estabelecimento",
                    "categoria": "Categoria",
                    "conta": "Conta",
                    "progresso": "Parcela",
                    "valor_parcela": st.column_config.NumberColumn("Valor Parcela", format="R$ %.2f"),
                    "parcelas_restantes": "Faltam",
                    "saldo_restante": st.column_config.NumberColumn("Saldo Restante", format="R$ %.2f"),
                    "termino_previsto": "Término",
                },
            )

    st.markdown("---")
    c_f1, c_f2 = st.columns(2)
    with c_f1:
        st.markdown("##### 🔒 Assinaturas & Custos Fixos Mensais")
        st.caption("Cobranças que se repetem ~1x por mês com valor estável.")
        if info_rec["fixos"].empty:
            st.info("Nenhum custo fixo recorrente identificado ainda.")
        else:
            st.dataframe(
                info_rec["fixos"],
                hide_index=True,
                use_container_width=True,
                column_config={
                    "estabelecimento": "Descrição",
                    "categoria": "Categoria",
                    "conta": "Conta",
                    "meses_cobrado": "Meses",
                    "media_mensal": st.column_config.NumberColumn("Média / Mês", format="R$ %.2f"),
                    "ultima_cobranca": st.column_config.DateColumn("Última", format="DD/MM/YYYY"),
                    "status": "Status",
                },
            )

    with c_f2:
        st.markdown("##### 🔄 Hábitos Recorrentes (Gastos Frequentes)")
        st.caption("Estabelecimentos onde você gasta com frequência ao longo dos meses.")
        if info_rec["habitos"].empty:
            st.info("Nenhum hábito recorrente identificado ainda.")
        else:
            st.dataframe(
                info_rec["habitos"].head(15),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "estabelecimento": "Estabelecimento",
                    "categoria": "Categoria",
                    "meses_cobrado": "Meses",
                    "ocorrencias": "Vezes",
                    "media_mensal": st.column_config.NumberColumn("Média / Mês", format="R$ %.2f"),
                    "total_historico": st.column_config.NumberColumn("Total Acum.", format="R$ %.2f"),
                    "status": "Status",
                },
            )

with tab_orc_metas:
    c_om1, c_om2 = st.columns([3, 2])
    with c_om1:
        st.subheader("📏 Orçamento Mensal")
        if orc_despesas.empty:
            st.info("Nenhum item de orçamento cadastrado na aba `orcamento`.")
        else:
            total_essencial = float(orc_despesas[orc_despesas["grupo"] == "Essencial"]["valor"].sum())
            total_estilo = float(orc_despesas[orc_despesas["grupo"] != "Essencial"]["valor"].sum())
            st.caption(
                f"Orçamento total de despesas: **R$ {teto_orcamento_mes:,.2f}** "
                f"(Essencial: R$ {total_essencial:,.2f} · Estilo de vida: R$ {total_estilo:,.2f})"
            )
            progresso = min(1.0, despesas_mes / teto_orcamento_mes) if teto_orcamento_mes > 0 else 0.0
            st.progress(
                progresso,
                text=f"Realizado em {mes_selecionado}: R$ {despesas_mes:,.2f} de R$ {teto_orcamento_mes:,.2f} ({progresso*100:.1f}%)",
            )
            st.dataframe(
                orc_despesas[["categoria", "grupo", "valor"]].sort_values(["grupo", "valor"], ascending=[True, False]),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "categoria": "Item do Orçamento",
                    "grupo": "Grupo",
                    "valor": st.column_config.NumberColumn("Valor Mensal", format="R$ %.2f"),
                },
            )

    with c_om2:
        st.subheader("🛡️ Reserva de Emergência & Metas")
        if df_metas.empty:
            st.info("Nenhuma meta cadastrada na aba `metas`.")
        else:
            for _, meta in df_metas.iterrows():
                alvo = float(meta["valor_alvo"] or 0.0)
                atual = float(meta["valor_atual"] or 0.0)
                pct = min(1.0, atual / alvo) if alvo > 0 else 0.0
                st.metric(
                    str(meta["nome"]),
                    f"R$ {atual:,.2f}",
                    delta=f"Meta: R$ {alvo:,.2f} ({pct*100:.1f}%)",
                )
                st.progress(pct)
                with st.form(f"form_meta_{meta['id']}"):
                    novo_val = st.number_input(
                        "Atualizar valor atual (R$)",
                        min_value=0.0,
                        value=atual,
                        step=100.0,
                        format="%.2f",
                    )
                    if st.form_submit_button("💾 Atualizar Meta"):
                        obter_repo().update_by_key("metas", str(meta["id"]), {"valor_atual": round(novo_val, 2)})
                        invalidar_abas("metas")
                        st.toast("✅ Meta atualizada!")
                        st.rerun()

with tab_extrato:
    st.subheader(f"Extrato de {mes_selecionado}")
    busca = st.text_input("🔍 Filtrar por descrição ou categoria", placeholder="Ex: Uber, Mercado, Pix...")

    df_ext = df_filtrado_contas[df_filtrado_contas["ano_mes"] == mes_selecionado].copy()
    if busca.strip():
        termo = busca.strip().lower()
        df_ext = df_ext[
            df_ext["descricao"].str.lower().str.contains(termo, na=False)
            | df_ext["categoria"].str.lower().str.contains(termo, na=False)
        ]

    cols_ext = ["id", "data", "descricao", "valor", "categoria", "conta", "meio", "origem", "transferencia"]
    df_ext_edit = st.data_editor(
        df_ext[cols_ext],
        hide_index=True,
        use_container_width=True,
        disabled=["id", "data", "valor", "conta", "meio", "origem"],
        column_config={
            "id": st.column_config.TextColumn("ID", width="small"),
            "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
            "descricao": st.column_config.TextColumn("Descrição", width="large"),
            "valor": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
            "categoria": st.column_config.SelectboxColumn("Categoria", options=TODAS_CATEGORIAS_V2, required=True),
            "conta": "Conta",
            "meio": "Meio",
            "origem": "Origem",
            "transferencia": st.column_config.SelectboxColumn("Transf.", options=["N", "S"]),
        },
        key=f"editor_extrato_{mes_selecionado}",
    )

    if st.button("💾 Salvar edições deste mês", type="primary"):
        repo = obter_repo()
        orig_map = df_ext.set_index("id")
        alteradas = 0
        for _, row in df_ext_edit.iterrows():
            tx_id = str(row["id"])
            orig = orig_map.loc[tx_id]
            mudancas = {}
            for col in ("descricao", "categoria", "transferencia"):
                if str(row[col]) != str(orig[col]):
                    mudancas[col] = str(row[col])
            if "categoria" in mudancas and mudancas["categoria"] == "Transferência Interna":
                mudancas["transferencia"] = "S"
            if mudancas:
                mudancas["atualizado_em"] = agora_iso()
                repo.update_by_key("transacoes", tx_id, mudancas)
                alteradas += 1
        invalidar_abas("transacoes")
        st.success(f"✅ {alteradas} transação(ões) atualizada(s)!")
        st.rerun()

# ==================== AÇÕES RÁPIDAS (PADRÃO NUTRIV3) ====================
st.divider()
st.subheader("⚡ Ações Rápidas")
qa1, qa2, qa3, qa4 = st.columns(4)
with qa1:
    if st.button("💸 Lançar / Importar Gastos", use_container_width=True):
        st.switch_page("pages/Inserting_Data.py")
with qa2:
    if st.button("📈 Carteira de Investimentos", use_container_width=True):
        st.switch_page("pages/Investimentos.py")
with qa3:
    if st.button("🤖 Consultor Financeiro IA", use_container_width=True):
        st.switch_page("pages/Gemini.py")
with qa4:
    if st.button("⚙️ Configurações & Orçamento", use_container_width=True):
        st.switch_page("pages/Configuracoes.py")
