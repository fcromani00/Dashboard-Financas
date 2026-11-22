import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import schema  # noqa: E402
from core.sheets import SchemaError, SheetsRepo  # noqa: E402


class FakeWorksheet:
    def __init__(self, title, rows=None):
        self.title = title
        self.rows = [list(r) for r in (rows or [])]

    def get_all_values(self, value_render_option=None):
        return [list(r) for r in self.rows]

    def row_values(self, i):
        return list(self.rows[i - 1]) if len(self.rows) >= i else []

    def col_values(self, j):
        return [r[j - 1] if len(r) >= j else "" for r in self.rows]

    def update(self, a1, values, value_input_option=None):
        assert a1 == "A1"
        if self.rows:
            self.rows[0] = list(values[0])
        else:
            self.rows.append(list(values[0]))

    def append_rows(self, linhas, value_input_option=None, insert_data_option=None):
        assert value_input_option == "RAW"
        self.rows.extend([list(l) for l in linhas])

    def batch_update(self, celulas, value_input_option=None):
        import gspread.utils as gu

        for c in celulas:
            r, col = gu.a1_to_rowcol(c["range"])
            while len(self.rows[r - 1]) < col:
                self.rows[r - 1].append("")
            self.rows[r - 1][col - 1] = c["values"][0][0]

    def freeze(self, rows=0):
        pass


class FakeSpreadsheet:
    def __init__(self):
        self.sheets = {}

    def worksheets(self):
        return list(self.sheets.values())

    def worksheet(self, nome):
        return self.sheets[nome]

    def add_worksheet(self, title, rows, cols):
        ws = FakeWorksheet(title)
        self.sheets[title] = ws
        return ws


class TestSheetsRepo(unittest.TestCase):
    def setUp(self):
        self.ss = FakeSpreadsheet()
        self.repo = SheetsRepo(self.ss)

    def test_cria_aba_append_e_le_tipado(self):
        self.assertTrue(self.repo.garantir_aba("transacoes"))
        self.assertFalse(self.repo.garantir_aba("transacoes"))
        n = self.repo.append(
            "transacoes",
            [{"id": "a1", "data": date(2026, 11, 22), "valor": -10.5, "descricao": "Café", "transferencia": False}],
        )
        self.assertEqual(n, 1)
        linha = self.ss.sheets["transacoes"].rows[1]
        self.assertEqual(linha[schema.TRANSACOES.columns.index("data")], "2026-11-22")
        self.assertEqual(linha[schema.TRANSACOES.columns.index("valor")], -10.5)
        self.assertEqual(linha[schema.TRANSACOES.columns.index("transferencia")], "N")

        df = self.repo.ler("transacoes")
        self.assertEqual(df.iloc[0]["data"], date(2026, 11, 22))
        self.assertEqual(df.iloc[0]["valor"], -10.5)

    def test_append_respeita_ordem_real_do_cabecalho(self):
        # Usuário reordenou colunas e adicionou uma extra na planilha
        header = list(reversed(schema.TRANSACOES.columns)) + ["minha_coluna"]
        self.ss.sheets["transacoes"] = FakeWorksheet("transacoes", [header])
        self.repo.append("transacoes", pd.DataFrame([{"id": "x", "valor": 1.0, "descricao": "ok"}]))
        linha = dict(zip(header, self.ss.sheets["transacoes"].rows[1]))
        self.assertEqual(linha["id"], "x")
        self.assertEqual(linha["descricao"], "ok")
        self.assertEqual(linha["minha_coluna"], "")

    def test_update_by_key_altera_so_a_linha(self):
        self.repo.garantir_aba("transacoes")
        self.repo.append("transacoes", [{"id": "a", "descricao": "A", "categoria": ""}, {"id": "b", "descricao": "B", "categoria": ""}])
        self.assertTrue(self.repo.update_by_key("transacoes", "b", {"categoria": "Lazer", "status": "confirmada"}))
        df = self.repo.ler("transacoes")
        self.assertEqual(df.set_index("id").loc["b", "categoria"], "Lazer")
        self.assertEqual(df.set_index("id").loc["a", "categoria"], "")
        self.assertFalse(self.repo.update_by_key("transacoes", "zzz", {"categoria": "X"}))

    def test_cabecalho_incompativel_bloqueia(self):
        self.ss.sheets["transacoes"] = FakeWorksheet("transacoes", [["id", "data"]])
        with self.assertRaises(SchemaError):
            self.repo.append("transacoes", [{"id": "1"}])


if __name__ == "__main__":
    unittest.main()
