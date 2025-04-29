#Dashboard finanças streamlit

import streamlit as st
import altair as alt
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from functions import gerar_relatorio_rag

st.set_page_config(page_title="Finanças Felipe", page_icon=":material/savings:", layout="wide", initial_sidebar_state="auto", menu_items=None)

if "df" not in st.session_state:
    conn = st.connection("gsheets", type=GSheetsConnection)
    df = conn.read(worksheet="df")
    st.session_state["df"] = df.copy()
else:
    df = st.session_state["df"].copy()

st.title('Dashboard Finanças')
st.write('Dashboard para visualização de dados financeiros')
st.write('[Planilha](https://docs.google.com/spreadsheets/d/1MbvWpJNs1TpQVkXnFw5HetFgBEyOCUKgA3G_pZh4mgo)')
st.write('---')

with st.sidebar:
    st.subheader("Filtros :material/filter_alt:")
    data_min, data_max = st.sidebar.date_input("Selecione o período",[pd.to_datetime(df["Data"]).min(), pd.to_datetime(df["Data"]).max()])
    categorias = df["Categoria"].unique()
    categoria_selecionada = st.sidebar.multiselect("Filtrar por Categoria", categorias, default=categorias)

    df = df[
    (pd.to_datetime(df["Data"]) >= pd.to_datetime(data_min)) & 
    (pd.to_datetime(df["Data"]) <= pd.to_datetime(data_max)) & 
    (df["Categoria"].isin(categoria_selecionada))
]



col1, col2, col3, col4 = st.columns(4)

with col1:
    saldo_atual = round(df["Valor"].sum(),2)
    st.metric("Saldo atual", saldo_atual)

df_mes = df[df["Ano/Mês"] == df["Ano/Mês"].max()]
with col2:
    receita_mensal = round(df_mes[df_mes["Valor"] > 0]["Valor"].sum(),2)
    st.metric("Receitas do mês", receita_mensal)

with col3:
    gastos_mensal = round(df_mes[df_mes["Valor"] < 0]["Valor"].sum(),2)
    st.metric("Gastos do mês", gastos_mensal)

with col4:
    saldo_mensal = round(receita_mensal + gastos_mensal,2)
    st.metric("Saldo do mês", saldo_mensal)

col1,col2,col3,col4 = st.columns([1,4,4,1])

with col2:
    df_categoria = df.groupby(['Categoria'])['Valor'].sum().reset_index()
    df_categoria = df_categoria.sort_values(by="Valor", ascending=False)
    chart = alt.Chart(df_categoria).mark_bar().encode(
    x=alt.X('Valor:Q', title="Total Gasto"),
    y=alt.Y('Categoria:N', sort='x'),  # Ordena
    tooltip=["Categoria", "Valor"]
).properties(
    title="Gastos por Categoria"
)
    st.altair_chart(chart, use_container_width=True)

with col3:
    df_faturas_por_anomes = df.groupby(['Ano/Mês'])['Valor'].sum().reset_index()
    df_faturas_por_anomes = df_faturas_por_anomes.sort_values(by="Ano/Mês", ascending=True)  # Ordena corretamente

    chart = alt.Chart(df_faturas_por_anomes).mark_bar().encode(
        x=alt.X('Ano/Mês:N', title="Ano/Mês", sort=None),  # 'N' (nominal) evita problemas de ordenação
        y=alt.Y('Valor:Q', title="Total Gasto"),
        tooltip=["Ano/Mês", "Valor"]
    ).properties(
        title="Gastos Mensais ao Longo do Tempo"
    )
    st.altair_chart(chart, use_container_width=True)

st.dataframe(df,hide_index=True)


if st.button('Gerar Excel'):
    df.to_excel('Nubank.xlsx', index=False)

if st.button('Gerar Relatório pro consultor'):
    
    st.write(gerar_relatorio_rag(st.session_state["df"]))