"""Finanças V2 — Aplicativo Principal com Autenticação Centralizada e Visual NutriV3."""

import streamlit as st

from core.auth import check_password, sidebar_usuario

st.set_page_config(
    page_title="Finanças Felipe",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="auto",
)

# CSS customizado inspirado no NutriV3 (paleta verde-esmeralda financeira)
st.markdown(
    """
<style>
    :root {
        --primary-color: #1B5E20;
        --secondary-color: #4CAF50;
    }
    .stButton > button {
        border-radius: 8px;
        font-weight: 500;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.65rem;
        font-weight: 700;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0 0;
        padding: 10px 18px;
    }
</style>
""",
    unsafe_allow_html=True,
)

# Bloqueio centralizado: nenhuma página ou menu aparece sem autenticação
if not check_password():
    st.stop()

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
