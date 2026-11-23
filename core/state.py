"""Gerenciamento de estado e cache do Streamlit para o Finanças V2.

Evita leituras repetidas na API do Google Sheets durante a navegação e invalida
apenas a aba que sofreu escrita.
"""

from __future__ import annotations

import os
import streamlit as st
import pandas as pd
from dotenv import load_dotenv

from core.sheets import SheetsRepo, abrir_planilha

load_dotenv()


@st.cache_resource(show_spinner=False)
def obter_repo() -> SheetsRepo:
    return SheetsRepo(abrir_planilha())


def ler_aba(nome_tab: str, forcar: bool = False) -> pd.DataFrame:
    chave = f"v2_tab_{nome_tab}"
    if forcar or chave not in st.session_state:
        repo = obter_repo()
        st.session_state[chave] = repo.ler(nome_tab)
    return st.session_state[chave].copy()


def invalidar_abas(*nomes_tabs: str) -> None:
    if not nomes_tabs:
        for k in list(st.session_state.keys()):
            if k.startswith("v2_tab_"):
                st.session_state.pop(k, None)
    else:
        for n in nomes_tabs:
            st.session_state.pop(f"v2_tab_{n}", None)


def mapa_config(forcar: bool = False) -> dict[str, str]:
    """Retorna a aba `config` como dicionário {chave: valor}."""
    df_cfg = ler_aba("config", forcar=forcar)
    if df_cfg.empty:
        return {}
    return {
        str(r["chave"]).strip(): str(r["valor"]).strip()
        for _, r in df_cfg.iterrows()
        if str(r.get("chave", "")).strip()
    }


def salvar_config(alteracoes: dict[str, str]) -> None:
    """Faz upsert de chaves na aba `config` usando update_by_key ou append."""
    repo = obter_repo()
    atuais = mapa_config(forcar=True)
    novos = []
    for chave, valor in alteracoes.items():
        chave_s = str(chave).strip()
        valor_s = str(valor).strip()
        if chave_s in atuais:
            repo.update_by_key("config", chave_s, {"valor": valor_s})
        else:
            novos.append({"chave": chave_s, "valor": valor_s})
    if novos:
        repo.append("config", novos)
    invalidar_abas("config")


def obter_groq_key() -> str | None:
    key = os.getenv("GROQ_API_KEY")
    if key:
        return key
    try:
        return st.secrets.get("GROQ_API_KEY") or st.secrets.get("secrets", {}).get("GROQ_API_KEY")
    except Exception:
        return None


def obter_gemini_key() -> str | None:
    key = os.getenv("GOOGLE_API_KEY")
    if key and key.strip():
        return key.strip()
    try:
        bruta = (
            st.secrets.get("GEMINI", {}).get("api_key")
            or st.secrets.get("secrets", {}).get("GOOGLE_API_KEY")
            or st.secrets.get("GOOGLE_API_KEY")
        )
        return str(bruta).strip() if bruta else None
    except Exception:
        return None
