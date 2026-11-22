"""Funções utilitárias puras (sem dependência de Streamlit ou Google)."""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

SHEETS_EPOCH = date(1899, 12, 30)
TZ_BR = timezone(timedelta(hours=-3))


def novo_id() -> str:
    """ID curto e aleatório (12 hex) para novas linhas."""
    return uuid.uuid4().hex[:12]


def id_deterministico(*partes: Any) -> str:
    """ID estável a partir de conteúdo (permite rodar a migração várias vezes com o mesmo resultado)."""
    base = "|".join(str(p) for p in partes)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def agora_iso() -> str:
    return datetime.now(TZ_BR).strftime("%Y-%m-%d %H:%M:%S")


def normalizar_texto(texto: Any) -> str:
    s = "" if texto is None or (isinstance(texto, float) and pd.isna(texto)) else str(texto)
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_numero(valor: Any) -> float | None:
    """Converte números em formato BR/US, 'R$', negativos com espaço não-quebrável etc."""
    if valor is None:
        return None
    if isinstance(valor, bool):
        return float(valor)
    if isinstance(valor, (int, float)):
        return None if pd.isna(valor) else float(valor)

    texto = str(valor).replace("R$", "").replace("US$", "").replace("$", "")
    texto = texto.replace("\xa0", "").replace(" ", "").strip()
    if not texto or texto.lower() in ("nan", "none", "-"):
        return None

    negativo = texto.startswith("-") or (texto.startswith("(") and texto.endswith(")"))
    texto = texto.strip("()").lstrip("+-")

    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(",", ".")

    try:
        num = float(texto)
    except ValueError:
        return None
    return -num if negativo else num


def parse_data(valor: Any) -> date | None:
    """Aceita date/datetime, serial do Sheets, ISO (AAAA-MM-DD), BR (DD/MM/AAAA) e US (M/D/AAAA com mes>12 impossível)."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, pd.Timestamp):
        return None if pd.isna(valor) else valor.date()
    if isinstance(valor, (int, float)):
        if pd.isna(valor):
            return None
        # Serial de data do Google Sheets (dias desde 1899-12-30)
        if 1 < valor < 100000:
            return SHEETS_EPOCH + timedelta(days=int(valor))
        return None

    texto = str(valor).strip()
    if not texto or texto.lower() in ("nan", "nat", "none"):
        return None

    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", texto)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", texto)
    if m:
        d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if mth > 12 and d <= 12:  # formato US
            d, mth = mth, d
        return date(y, mth, d)

    try:
        return pd.to_datetime(texto, dayfirst=True).date()
    except (ValueError, TypeError):
        return None


def hash_dedup(data_tx: date | str | None, valor: float | None, descricao: Any, conta: Any = "") -> str:
    d = data_tx.isoformat() if isinstance(data_tx, date) else str(data_tx or "")
    v = f"{(valor or 0.0):.2f}"
    return hashlib.sha1(f"{d}|{v}|{normalizar_texto(descricao)}|{normalizar_texto(conta)}".encode("utf-8")).hexdigest()[:16]


def hash_arquivo(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()[:20]


def vazio(valor: Any) -> bool:
    if valor is None:
        return True
    if isinstance(valor, float) and pd.isna(valor):
        return True
    return str(valor).strip() in ("", "nan", "None", "NaT")
