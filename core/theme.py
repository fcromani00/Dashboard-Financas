"""Tema visual V2 inspirado no Banco Inter com alternância Dark / Light e badges SVG."""

from __future__ import annotations

import streamlit as st

_PALETAS = {
    "dark": {
        "bg": "#0F1115",
        "surface": "#181B22",
        "surface_alt": "#1F242E",
        "border": "#2A2F3B",
        "text": "#F3F4F6",
        "muted": "#9CA3AF",
        "accent": "#FF7A00",
        "accent_soft": "rgba(255, 122, 0, 0.14)",
        "positive": "#10B981",
        "negative": "#EF4444",
        "shadow": "0 2px 10px rgba(0, 0, 0, 0.28)",
    },
    "light": {
        "bg": "#F8FAFC",
        "surface": "#FFFFFF",
        "surface_alt": "#F1F5F9",
        "border": "#E2E8F0",
        "text": "#0F172A",
        "muted": "#64748B",
        "accent": "#FF7A00",
        "accent_soft": "rgba(255, 122, 0, 0.10)",
        "positive": "#059669",
        "negative": "#DC2626",
        "shadow": "0 1px 6px rgba(15, 23, 42, 0.06)",
    },
}


def tema_atual() -> str:
    if "tema_ui" not in st.session_state:
        st.session_state["tema_ui"] = "dark"
    return str(st.session_state["tema_ui"])


def seletor_tema_sidebar() -> str:
    """Renderiza o alternador Dark / Light na barra lateral."""
    atual = tema_atual()
    modo_claro = st.sidebar.toggle("Modo claro", value=(atual == "light"), key="_toggle_tema_ui")
    st.session_state["tema_ui"] = "light" if modo_claro else "dark"
    return st.session_state["tema_ui"]


def aplicar_tema_css() -> None:
    """Injeta CSS limpo para Dark/Light estilo Inter (cards de métricas, abas, botões e expanders)."""
    modo = tema_atual()
    p = _PALETAS[modo]
    st.markdown(
        f"""
<style>
    :root {{
        --app-bg: {p["bg"]};
        --app-surface: {p["surface"]};
        --app-surface-alt: {p["surface_alt"]};
        --app-border: {p["border"]};
        --app-text: {p["text"]};
        --app-muted: {p["muted"]};
        --app-accent: {p["accent"]};
    }}
    .stApp, [data-testid="stAppViewContainer"] {{
        background-color: {p["bg"]};
        color: {p["text"]};
    }}
    [data-testid="stHeader"] {{
        background-color: transparent;
    }}
    [data-testid="stSidebar"] {{
        background-color: {p["surface"]};
        border-right: 1px solid {p["border"]};
    }}
    [data-testid="stSidebar"] * {{
        color: {p["text"]};
    }}
    /* Cards de KPI */
    [data-testid="stMetric"] {{
        background-color: {p["surface"]};
        border: 1px solid {p["border"]};
        border-radius: 12px;
        padding: 14px 16px;
        box-shadow: {p["shadow"]};
    }}
    [data-testid="stMetricLabel"] {{
        color: {p["muted"]} !important;
        font-size: 0.84rem !important;
        font-weight: 500 !important;
    }}
    [data-testid="stMetricValue"] {{
        color: {p["text"]} !important;
        font-size: 1.55rem !important;
        font-weight: 700 !important;
    }}
    /* Containers com borda e Expanders */
    [data-testid="stVerticalBlockBorderWrapper"] {{
        background-color: {p["surface"]};
        border-color: {p["border"]} !important;
        border-radius: 12px !important;
    }}
    [data-testid="stExpander"] {{
        background-color: {p["surface"]};
        border: 1px solid {p["border"]} !important;
        border-radius: 10px !important;
    }}
    /* Botões */
    .stButton > button, .stDownloadButton > button {{
        border-radius: 8px;
        font-weight: 600;
        border: 1px solid {p["border"]};
    }}
    .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {{
        background-color: {p["accent"]} !important;
        border-color: {p["accent"]} !important;
        color: #FFFFFF !important;
    }}
    /* Abas */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 6px;
        border-bottom: 1px solid {p["border"]};
        padding-bottom: 2px;
    }}
    .stTabs [data-baseweb="tab"] {{
        border-radius: 8px 8px 0 0;
        padding: 8px 14px;
        color: {p["muted"]};
        font-weight: 500;
    }}
    .stTabs [aria-selected="true"] {{
        color: {p["accent"]} !important;
        background-color: {p["accent_soft"]} !important;
        font-weight: 600;
    }}
    /* Logo / Badge na sidebar */
    .brand-header {{
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 4px 0 12px 0;
        margin-bottom: 8px;
        border-bottom: 1px solid {p["border"]};
    }}
    .brand-icon {{
        width: 34px;
        height: 34px;
        border-radius: 10px;
        background: linear-gradient(135deg, #FF7A00 0%, #FF9E2C 100%);
        display: flex;
        align-items: center;
        justify-content: center;
        color: #FFFFFF;
        font-weight: 800;
        font-size: 1.05rem;
        flex-shrink: 0;
    }}
    .inst-badge {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: 0.76rem;
        font-weight: 600;
        letter-spacing: 0.01em;
    }}
</style>
""",
        unsafe_allow_html=True,
    )


def render_brand_sidebar() -> None:
    """Exibe cabeçalho de marca estilizado no topo da sidebar."""
    st.sidebar.markdown(
        """
<div class="brand-header">
  <div class="brand-icon">F</div>
  <div>
    <div style="font-weight:700; font-size:1.02rem; line-height:1.15;">Finanças</div>
    <div style="font-size:0.75rem; opacity:0.7;">Patrimônio & Orçamento</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def badge_instituicao_html(conta: str) -> str:
    """Retorna HTML de badge colorido com mini-ícone SVG para Inter, Mercado Pago ou Binance."""
    c = (conta or "").lower()
    if "inter" in c:
        cor, bg, letra, nome = "#FF7A00", "rgba(255,122,0,0.16)", "i", conta
    elif "mercado" in c:
        cor, bg, letra, nome = "#009EE3", "rgba(0,158,227,0.16)", "M", conta
    elif "binance" in c:
        cor, bg, letra, nome = "#F0B90B", "rgba(240,185,11,0.16)", "B", conta
    else:
        cor, bg, letra, nome = "#10B981", "rgba(16,185,129,0.16)", "$", conta

    return (
        f'<span class="inst-badge" style="background:{bg}; color:{cor}; border:1px solid {cor}44;">'
        f'<span style="display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;'
        f'border-radius:50%;background:{cor};color:#fff;font-size:0.65rem;font-weight:800;">{letra}</span>'
        f"{nome}</span>"
    )
