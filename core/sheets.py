"""Repositório de acesso ao Google Sheets com escrita segura.

Regras de ouro:
- NUNCA reescreve uma aba inteira: só `append` (novas linhas) ou `update_by_key` (linha específica).
- Antes de escrever, confere se o cabeçalho da aba bate com o esquema.
- Grava números como números e datas como texto ISO (value_input_option RAW).
"""

from __future__ import annotations

import tomllib
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from core.schema import ALL_TABS, Tab
from core.utils import parse_data, parse_numero, vazio

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

ROOT = Path(__file__).resolve().parent.parent
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"


class SchemaError(RuntimeError):
    pass


def carregar_credenciais(secrets_path: Path = SECRETS_PATH) -> dict[str, Any]:
    """Lê a seção [connections.gsheets] do secrets.toml (fora do Streamlit) ou de st.secrets."""
    try:
        import streamlit as st  # noqa: WPS433

        if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
            return dict(st.secrets["connections"]["gsheets"])
    except Exception:
        pass

    with open(secrets_path, "rb") as fh:
        dados = tomllib.load(fh)
    return dict(dados["connections"]["gsheets"])


def _spreadsheet_key(cfg: dict[str, Any]) -> str:
    if cfg.get("spreadsheet_id"):
        return str(cfg["spreadsheet_id"])
    url = str(cfg.get("spreadsheet", ""))
    if "/d/" in url:
        return url.split("/d/")[1].split("/")[0]
    raise SchemaError("Configure 'spreadsheet_id' ou 'spreadsheet' em [connections.gsheets].")


def abrir_planilha(cfg: dict[str, Any] | None = None):
    import gspread
    from google.oauth2.service_account import Credentials

    cfg = cfg or carregar_credenciais()
    campos_sa = {
        k: cfg[k]
        for k in (
            "type",
            "project_id",
            "private_key_id",
            "private_key",
            "client_email",
            "client_id",
            "auth_uri",
            "token_uri",
            "universe_domain",
        )
        if k in cfg
    }
    creds = Credentials.from_service_account_info(campos_sa, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(_spreadsheet_key(cfg))


def _celula_para_sheet(valor: Any) -> Any:
    """Converte valores Python/pandas em tipos aceitos pela API (RAW)."""
    if vazio(valor):
        return ""
    if isinstance(valor, (datetime, pd.Timestamp)):
        return valor.strftime("%Y-%m-%d")
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, bool):
        return "S" if valor else "N"
    if hasattr(valor, "item"):  # numpy scalars
        return valor.item()
    return valor


def tipar_dataframe(df: pd.DataFrame, tab: Tab) -> pd.DataFrame:
    df = df.copy()
    for col in tab.columns:
        if col not in df.columns:
            df[col] = ""
    for col in tab.numeric:
        df[col] = df[col].apply(parse_numero)
    for col in tab.dates:
        df[col] = df[col].apply(parse_data)
    texto = [c for c in tab.columns if c not in tab.numeric and c not in tab.dates]
    for col in texto:
        df[col] = df[col].apply(lambda v: "" if vazio(v) else str(v))
    return df[tab.columns + [c for c in df.columns if c not in tab.columns]]


class SheetsRepo:
    """Acesso tipado às abas V2. Recebe um objeto `gspread.Spreadsheet` (ou um fake nos testes)."""

    def __init__(self, spreadsheet):
        self.ss = spreadsheet
        self._ws_cache: dict[str, Any] = {}

    # ------------------------------------------------------------------ leitura
    def worksheet(self, nome: str):
        if nome not in self._ws_cache:
            self._ws_cache[nome] = self.ss.worksheet(nome)
        return self._ws_cache[nome]

    def nomes_abas(self) -> list[str]:
        return [ws.title for ws in self.ss.worksheets()]

    def ler_grade(self, nome: str) -> pd.DataFrame:
        """Lê uma aba em formato de planilha livre (removendo colunas 100% vazias como faz o
        st-gsheets-connection), preservando os índices posicionais de `Orçamento Financeiro Mensal`.
        """
        ws = self.worksheet(nome)
        valores = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
        if not valores or len(valores) < 2:
            return pd.DataFrame()
        largura = max(len(r) for r in valores)
        matriz = [r + [""] * (largura - len(r)) for r in valores]
        cols_nao_vazias = [
            j for j in range(largura) if not all(vazio(matriz[i][j]) for i in range(len(matriz)))
        ]
        linhas = [[r[j] for j in cols_nao_vazias] for r in matriz[1:]]
        cols = [str(matriz[0][j]).strip() or f"col_{idx}" for idx, j in enumerate(cols_nao_vazias)]
        return pd.DataFrame(linhas, columns=cols)

    def ler_bruto(self, nome: str) -> pd.DataFrame:
        """Lê qualquer aba (inclusive V1) com valores não formatados."""
        ws = self.worksheet(nome)
        valores = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
        if not valores:
            return pd.DataFrame()
        header = [str(h).strip() for h in valores[0]]
        linhas = [row + [""] * (len(header) - len(row)) for row in valores[1:]]
        df = pd.DataFrame(linhas, columns=header)
        df = df.loc[:, [c for c in df.columns if c != ""]]
        # remove linhas totalmente vazias
        return df[~df.apply(lambda r: all(vazio(v) for v in r), axis=1)].reset_index(drop=True)

    def ler(self, nome_tab: str) -> pd.DataFrame:
        tab = ALL_TABS[nome_tab]
        df = self.ler_bruto(nome_tab)
        if df.empty:
            return pd.DataFrame(columns=tab.columns)
        self._validar_header(list(df.columns), tab)
        return tipar_dataframe(df, tab)

    # ------------------------------------------------------------------ estrutura
    def _validar_header(self, header: list[str], tab: Tab) -> None:
        faltando = [c for c in tab.columns if c not in header]
        if faltando:
            raise SchemaError(f"Aba '{tab.name}' sem as colunas {faltando}. Cabeçalho atual: {header}")

    def garantir_aba(self, nome_tab: str) -> bool:
        """Cria a aba com cabeçalho se não existir. Retorna True se criou."""
        tab = ALL_TABS[nome_tab]
        if nome_tab in self.nomes_abas():
            header = self.worksheet(nome_tab).row_values(1)
            if not header:
                self.worksheet(nome_tab).update("A1", [tab.columns], value_input_option="RAW")
                return False
            self._validar_header([str(h).strip() for h in header], tab)
            return False
        ws = self.ss.add_worksheet(title=nome_tab, rows=1000, cols=max(len(tab.columns), 5))
        ws.update("A1", [tab.columns], value_input_option="RAW")
        ws.freeze(rows=1)
        self._ws_cache[nome_tab] = ws
        return True

    # ------------------------------------------------------------------ escrita segura
    def _header(self, nome_tab: str) -> list[str]:
        header = [str(h).strip() for h in self.worksheet(nome_tab).row_values(1)]
        self._validar_header(header, ALL_TABS[nome_tab])
        return header

    def append(self, nome_tab: str, registros: pd.DataFrame | Iterable[dict[str, Any]], chunk: int = 500) -> int:
        """Acrescenta linhas no fim da aba respeitando a ordem real do cabeçalho."""
        df = registros if isinstance(registros, pd.DataFrame) else pd.DataFrame(list(registros))
        if df.empty:
            return 0
        header = self._header(nome_tab)
        linhas = [[_celula_para_sheet(row.get(col, "")) for col in header] for _, row in df.iterrows()]
        ws = self.worksheet(nome_tab)
        for i in range(0, len(linhas), chunk):
            ws.append_rows(linhas[i : i + chunk], value_input_option="RAW", insert_data_option="INSERT_ROWS")
        return len(linhas)

    def update_by_key(self, nome_tab: str, chave: str, alteracoes: dict[str, Any]) -> bool:
        """Atualiza apenas as células alteradas de UMA linha, localizada pela coluna-chave."""
        tab = ALL_TABS[nome_tab]
        if tab.key is None:
            raise SchemaError(f"Aba '{nome_tab}' não tem coluna-chave.")
        header = self._header(nome_tab)
        ws = self.worksheet(nome_tab)
        col_idx = header.index(tab.key) + 1
        coluna = ws.col_values(col_idx)
        try:
            linha = coluna.index(str(chave)) + 1
        except ValueError:
            return False
        if linha == 1:
            return False

        import gspread.utils as gu

        celulas = []
        for col, val in alteracoes.items():
            if col not in header:
                raise SchemaError(f"Coluna '{col}' não existe na aba '{nome_tab}'.")
            a1 = gu.rowcol_to_a1(linha, header.index(col) + 1)
            celulas.append({"range": a1, "values": [[_celula_para_sheet(val)]]})
        if celulas:
            ws.batch_update(celulas, value_input_option="RAW")
        return True

    def delete_by_column_value(self, nome_tab: str, coluna: str, valor: str) -> int:
        """Remove apenas as linhas onde `coluna == valor`, de baixo para cima (sem reescrever a aba)."""
        header = self._header(nome_tab)
        if coluna not in header:
            raise SchemaError(f"Coluna '{coluna}' não existe na aba '{nome_tab}'.")
        ws = self.worksheet(nome_tab)
        col_idx = header.index(coluna) + 1
        valores_col = ws.col_values(col_idx)
        linhas_alvo = [
            idx + 1
            for idx, v in enumerate(valores_col)
            if idx > 0 and str(v).strip() == str(valor).strip()
        ]
        for linha in sorted(linhas_alvo, reverse=True):
            ws.delete_rows(linha)
        return len(linhas_alvo)
