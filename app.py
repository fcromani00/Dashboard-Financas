"""Finanças V2 — Aplicativo Principal com Autenticação Centralizada e Visual NutriV3."""

import streamlit as st

from core.auth import check_password, sidebar_usuario
from core.theme import aplicar_tema_css, render_brand_sidebar, seletor_tema_sidebar

st.set_page_config(
    page_title="Finanças Felipe",
    page_icon="🟠",
    layout="wide",
    initial_sidebar_state="auto",
)

# Bloqueio centralizado: nenhuma página ou menu aparece sem autenticação
if not check_password():
    aplicar_tema_css()
    st.stop()

render_brand_sidebar()
seletor_tema_sidebar()
aplicar_tema_css()
sidebar_usuario()

pagina_hoje = st.Page(
    "pages/main.py",
    title="Visão Geral & Orçamento",
    icon=":material/savings:",
    default=not bool(st.query_params.get("valor") or st.query_params.get("acao") == "lancar"),
)

pagina_gastos = st.Page(
    "pages/Inserting_Data.py",
    title="Lançar & Importar Gastos",
    icon=":material/upload_file:",
    default=bool(st.query_params.get("valor") or st.query_params.get("acao") == "lancar"),
)

pagina_investimentos = st.Page(
    "pages/Investimentos.py",
    title="Carteira de Investimentos",
    icon=":material/trending_up:",
)

pagina_consultor = st.Page(
    "pages/Gemini.py",
    title="Consultor IA",
    icon=":material/smart_toy:",
)

pagina_config = st.Page(
    "pages/Configuracoes.py",
    title="Configurações",
    icon=":material/settings:",
)

pg = st.navigation(
    {
        "Principal": [pagina_hoje, pagina_gastos, pagina_investimentos],
        "Inteligência": [pagina_consultor],
        "Sistema": [pagina_config],
    }
)

pg.run()
