import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import schema  # noqa: E402
from core.migration import (  # noqa: E402
    catalogo_categorias,
    fatiar_orcamento_v1,
    migrar_investimentos,
    migrar_orcamento,
    migrar_transacoes,
    migrar_tudo,
)
from core.utils import parse_data, parse_numero  # noqa: E402


def df_v1_exemplo() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Data": "2026-11-20", "Descrição": "Padaria", "Valor": -45.9, "Categoria": "Alimentação", "Fonte": "Apple Pay", "Conta": "Nubank", "Dia da Semana": "Sexta", "Ano/Mês": "2026-11", "Tipo Transação": "iPhone (Apple Pay)"},
            {"Data": 46345, "Descrição": "Uber", "Valor": "-22,50", "Categoria": "Transporte", "Fonte": "Crédito", "Conta": "Nubank", "Dia da Semana": "", "Ano/Mês": "2026-11", "Tipo Transação": ""},
            {"Data": "05/11/2026", "Descrição": "Salário", "Valor": 5000, "Categoria": "Salário", "Fonte": "Extrato", "Conta": "Inter", "Dia da Semana": "", "Ano/Mês": "2026-11", "Tipo Transação": ""},
            {"Data": "2026-10-03", "Descrição": "Transferência enviada pelo Pix - FELIPE ROMANI", "Valor": -1000, "Categoria": "", "Fonte": "Extrato", "Conta": "Nubank", "Dia da Semana": "", "Ano/Mês": "2026-10", "Tipo Transação": ""},
            {"Data": "2026-10-04", "Descrição": "Café", "Valor": -8, "Categoria": "Cafeteria", "Fonte": "Crédito", "Conta": "Nubank", "Dia da Semana": "", "Ano/Mês": "2026-10", "Tipo Transação": ""},
            {"Data": "2026-10-04", "Descrição": "Café", "Valor": -8, "Categoria": "Cafeteria", "Fonte": "Crédito", "Conta": "Nubank", "Dia da Semana": "", "Ano/Mês": "2026-10", "Tipo Transação": ""},
            {"Data": "", "Descrição": "lixo", "Valor": "", "Categoria": "", "Fonte": "", "Conta": "", "Dia da Semana": "", "Ano/Mês": "", "Tipo Transação": ""},
        ]
    )


class TestUtils(unittest.TestCase):
    def test_parse_numero(self):
        self.assertEqual(parse_numero("R$ 1.234,56"), 1234.56)
        self.assertEqual(parse_numero("-\xa010,00"), -10.0)
        self.assertEqual(parse_numero("1,234.56"), 1234.56)
        self.assertEqual(parse_numero("0,11944"), 0.11944)
        self.assertIsNone(parse_numero(""))

    def test_parse_data(self):
        self.assertEqual(parse_data("2026-11-22"), date(2026, 11, 22))
        self.assertEqual(parse_data("22/11/2026"), date(2026, 11, 22))
        self.assertEqual(parse_data(45658), date(2025, 1, 1))  # serial do Sheets
        self.assertEqual(parse_data("9/30/2025"), date(2025, 9, 30))
        self.assertIsNone(parse_data(""))


class TestMigracaoTransacoes(unittest.TestCase):
    def test_transacoes(self):
        tx, avisos = migrar_transacoes(df_v1_exemplo(), padroes_transferencia=["Felipe Romani"])
        self.assertEqual(len(tx), 6)
        self.assertEqual(list(tx.columns), schema.TRANSACOES.columns)
        self.assertTrue(tx["id"].is_unique, "IDs devem ser únicos mesmo para linhas idênticas")

        padaria = tx[tx["descricao"] == "Padaria"].iloc[0]
        self.assertEqual(padaria["origem"], "iphone")
        self.assertEqual(padaria["meio"], "apple_pay")
        self.assertEqual(padaria["status"], "confirmada")

        uber = tx[tx["descricao"] == "Uber"].iloc[0]
        self.assertEqual(uber["valor"], -22.5)
        self.assertEqual(uber["data"], parse_data(46345))

        transf = tx[tx["descricao"].str.contains("FELIPE")].iloc[0]
        self.assertEqual(transf["transferencia"], "S")
        self.assertEqual(transf["categoria"], "Transferência Interna")

        self.assertTrue(any("idênticas" in a for a in avisos))
        self.assertTrue(any("ignorada" in a for a in avisos))

    def test_ids_estaveis(self):
        a, _ = migrar_transacoes(df_v1_exemplo())
        b, _ = migrar_transacoes(df_v1_exemplo())
        self.assertEqual(sorted(a["id"]), sorted(b["id"]))

    def test_categorias_preserva_existentes(self):
        tx, _ = migrar_transacoes(df_v1_exemplo())
        cats = catalogo_categorias(tx)
        self.assertIn("Cafeteria", cats["nome"].tolist())
        self.assertTrue(cats["nome"].is_unique)


class TestMigracaoInvestimentos(unittest.TestCase):
    def test_operacoes(self):
        inv = pd.DataFrame(
            [
                {"Trade Date": "2025-08-01", "Symbol": "PG", "Security": "PROCTER AND GAMBLE CO COM", "Action": "Buy", "Price": "150,00", "Quantity": "2"},
                {"Trade Date": "2025-09-10", "Symbol": "PG", "Security": "PROCTER AND GAMBLE CO COM", "Action": "Sell", "Price": "160,5", "Quantity": "-0,5"},
                {"Trade Date": "2025-09-10", "Symbol": "BRK.B", "Security": "BERKSHIRE", "Action": "Buy", "Price": "480", "Quantity": "1"},
            ]
        )
        ativos, ops, avisos = migrar_investimentos(inv)
        self.assertEqual(avisos, [])
        self.assertEqual(len(ops), 3)
        venda = ops[ops["tipo"] == "venda"].iloc[0]
        self.assertEqual(venda["quantidade"], 0.5)
        self.assertEqual(venda["valor_total"], 80.25)
        brk = ativos[ativos["ticker"] == "BRK.B"].iloc[0]
        self.assertEqual(brk["codigo_cotacao"], "BRK-B")
        self.assertIn("BTC", ativos["ticker"].tolist())
        self.assertIn("PORQUINHO-INTER", ativos["ticker"].tolist())
        self.assertIn("CDB-MP", ativos["ticker"].tolist())


class TestOrcamento(unittest.TestCase):
    def test_fatiamento_e_migracao(self):
        grade = pd.DataFrame("", index=range(40), columns=[f"c{i}" for i in range(6)])
        grade.iloc[4, 0:2] = ["Salário", "8000"]
        grade.iloc[4, 3:6] = ["ESSENCIAL", "Aluguel", "2500"]
        grade.iloc[5, 3:6] = ["NÃO ESSENCIAL", "Lazer", "400"]
        grade.iloc[16, 0:2] = ["RESERVA DE EMERGÊNCIA IDEAL", "30000"]
        grade.iloc[17, 0:2] = ["RESERVA DE EMERGÊNCIA ATUAL", "12000"]
        grade.iloc[24, 0:2] = ["Nome", "Felipe"]
        orc, metas, config = migrar_orcamento(fatiar_orcamento_v1(grade))
        self.assertEqual(len(orc), 3)
        self.assertEqual(orc[orc["categoria"] == "Lazer"].iloc[0]["grupo"], "Estilo de vida")
        self.assertEqual(metas.iloc[0]["valor_alvo"], 30000)
        self.assertEqual(metas.iloc[0]["valor_atual"], 12000)
        self.assertIn("perfil.nome", config["chave"].tolist())


class TestMigrarTudo(unittest.TestCase):
    def test_conferencia_bate(self):
        res = migrar_tudo(df_v1_exemplo(), None, None)
        self.assertEqual(res.relatorio["meses_divergentes"], 0)
        self.assertEqual(set(res.tabelas), set(schema.ALL_TABS))
        for nome, df in res.tabelas.items():
            self.assertEqual(list(df.columns)[: len(schema.ALL_TABS[nome].columns)], schema.ALL_TABS[nome].columns, nome)


if __name__ == "__main__":
    unittest.main()
