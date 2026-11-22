import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import schema  # noqa: E402
from core.portfolio import (  # noqa: E402
    calcular_evolucao_aportes_mensal,
    calcular_posicoes,
    calcular_rebalanceamento,
    consolidar_carteira,
)
from core.sheets import SheetsRepo  # noqa: E402
from core.transactions import (  # noqa: E402
    classificar_e_reconciliar_v2,
    criar_registro_transacao,
    gravar_lote_importado,
)
from tests.test_sheets import FakeSpreadsheet  # noqa: E402


class FakeWorksheetWithDelete:
    def __init__(self, ws):
        self._ws = ws

    def __getattr__(self, name):
        return getattr(self._ws, name)

    def delete_rows(self, row_idx):
        del self._ws.rows[row_idx - 1]


class TestTransactionsV2(unittest.TestCase):
    def setUp(self):
        self.ss = FakeSpreadsheet()
        self.repo = SheetsRepo(self.ss)
        for tab in ("transacoes", "importacoes", "regras"):
            self.repo.garantir_aba(tab)
            self.ss.sheets[tab] = FakeWorksheetWithDelete(self.ss.sheets[tab])
            self.repo._ws_cache[tab] = self.ss.sheets[tab]

    def test_regras_historico_e_conciliacao_iphone(self):
        # 1. Cadastra uma regra e um lançamento provisório do iPhone
        self.repo.append(
            "regras",
            [{"id": "r1", "padrao": "spotify", "categoria": "Assinaturas", "prioridade": 10, "ativa": "S"}],
        )
        reg_iphone = criar_registro_transacao(
            data_tx=date(2026, 11, 20),
            valor=-45.90,
            descricao="Padaria",
            categoria="Alimentação",
            conta="Nubank",
            meio="apple_pay",
            origem="iphone",
            status="provisoria",
        )
        reg_hist = criar_registro_transacao(
            data_tx=date(2026, 11, 10),
            valor=-25.00,
            descricao="Uber *Trip",
            categoria="Transporte",
            conta="Nubank",
            meio="credito",
            origem="import",
            status="confirmada",
        )
        self.repo.append("transacoes", [reg_iphone, reg_hist])

        df_tx = self.repo.ler("transacoes")
        df_regras = self.repo.ler("regras")

        # 2. Lote novo vindo da fatura
        df_lote = pd.DataFrame(
            [
                # Match com iPhone (+1 dia, mesmo valor)
                {"data": date(2026, 11, 21), "valor": -45.90, "descricao": "PADARIA CENTRAL LTDA", "categoria": "", "conta": "Nubank", "meio": "credito", "observacao": ""},
                # Match por regra (spotify -> Assinaturas)
                {"data": date(2026, 11, 21), "valor": -21.90, "descricao": "Spotify Brasil", "categoria": "", "conta": "Nubank", "meio": "credito", "observacao": ""},
                # Match por histórico (Uber -> Transporte)
                {"data": date(2026, 11, 22), "valor": -32.00, "descricao": "Uber *Trip", "categoria": "", "conta": "Nubank", "meio": "credito", "observacao": ""},
                # Transferência própria
                {"data": date(2026, 11, 22), "valor": -500.00, "descricao": "Pix enviado Felipe Christofaro Romani", "categoria": "", "conta": "Inter", "meio": "pix", "observacao": ""},
            ]
        )

        df_rec, stats = classificar_e_reconciliar_v2(df_lote, df_tx, df_regras=df_regras, groq_api_key=None)
        self.assertEqual(df_rec.at[0, "Status"], "📱 Conciliar c/ iPhone")
        self.assertEqual(df_rec.at[0, "conciliada_com"], reg_iphone["id"])
        self.assertEqual(df_rec.at[0, "categoria"], "Alimentação")
        self.assertEqual(df_rec.at[1, "categoria"], "Assinaturas")
        self.assertEqual(df_rec.at[2, "categoria"], "Transporte")
        self.assertEqual(df_rec.at[3, "categoria"], "Transferência Interna")

        # 3. Gravar lote: deve atualizar o registro do iPhone in-place e fazer append das outras 3
        imp_id, n_ins, n_conc = gravar_lote_importado(
            self.repo,
            df_rec[df_rec["Incluir"] == True],
            nome_arquivo="fatura_nov.csv",
            hash_arq="h123",
            formato="Fatura Nubank",
        )
        self.assertEqual(n_conc, 1)
        self.assertEqual(n_ins, 3)

        df_pos = self.repo.ler("transacoes")
        # 2 iniciais + 3 novas (o do iPhone foi atualizado in-place, sem duplicar!) = 5
        self.assertEqual(len(df_pos), 5)
        linha_conc = df_pos.set_index("id").loc[reg_iphone["id"]]
        self.assertEqual(linha_conc["status"], "confirmada")
        self.assertEqual(linha_conc["descricao"], "PADARIA CENTRAL LTDA")

        # 4. Desfazer importação
        removidas = self.repo.delete_by_column_value("transacoes", "importacao_id", imp_id)
        self.assertEqual(removidas, 4)


class TestPortfolioV2(unittest.TestCase):
    def test_compra_venda_renda_fixa_e_btc(self):
        df_ativos = pd.DataFrame(
            [
                {"id": "a_aapl", "ticker": "AAPL", "nome": "Apple", "classe": "acao_us", "moeda": "USD", "conta": "Inter US", "fonte_cotacao": "yfinance", "codigo_cotacao": "AAPL", "ativo": "S"},
                {"id": "a_rf", "ticker": "PORQUINHO-INTER", "nome": "Porquinho Inter", "classe": "renda_fixa", "moeda": "BRL", "conta": "Inter Porquinho", "fonte_cotacao": "cdi", "codigo_cotacao": "CDI", "ativo": "S"},
                {"id": "a_btc", "ticker": "BTC", "nome": "Bitcoin", "classe": "cripto", "moeda": "BRL", "conta": "Binance", "fonte_cotacao": "yfinance", "codigo_cotacao": "BTC-BRL", "ativo": "S"},
            ]
        )
        df_ops = pd.DataFrame(
            [
                # Compra 2 AAPL a $100 e depois vende 1 AAPL a $150 -> resta 1 AAPL com PM $100 e P&L realizado $50
                {"id": "1", "data": "2026-01-10", "ativo_id": "a_aapl", "conta": "Inter US", "tipo": "compra", "quantidade": 2, "preco": 100, "taxas": 0, "valor_total": 200, "moeda": "USD", "criado_em": "1"},
                {"id": "2", "data": "2026-02-10", "ativo_id": "a_aapl", "conta": "Inter US", "tipo": "venda", "quantidade": 1, "preco": 150, "taxas": 0, "valor_total": 150, "moeda": "USD", "criado_em": "2"},
                # Aporte R$ 1000 no Porquinho e depois ajuste de saldo para R$ 1080
                {"id": "3", "data": "2026-01-15", "ativo_id": "a_rf", "conta": "Inter Porquinho", "tipo": "aporte", "quantidade": 1, "preco": 1000, "taxas": 0, "valor_total": 1000, "moeda": "BRL", "criado_em": "3"},
                {"id": "4", "data": "2026-03-15", "ativo_id": "a_rf", "conta": "Inter Porquinho", "tipo": "ajuste_saldo", "quantidade": 1, "preco": 1080, "taxas": 0, "valor_total": 1080, "moeda": "BRL", "criado_em": "4"},
                # Compra 0.01 BTC por R$ 5.000 (PM R$ 500.000)
                {"id": "5", "data": "2026-03-20", "ativo_id": "a_btc", "conta": "Binance", "tipo": "compra", "quantidade": 0.01, "preco": 500000, "taxas": 0, "valor_total": 5000, "moeda": "BRL", "criado_em": "5"},
            ]
        )

        pos = calcular_posicoes(df_ativos, df_ops).set_index("ticker")
        self.assertEqual(pos.loc["AAPL", "quantidade"], 1.0)
        self.assertEqual(pos.loc["AAPL", "preco_medio"], 100.0)
        self.assertEqual(pos.loc["AAPL", "pl_realizado"], 50.0)
        self.assertEqual(pos.loc["PORQUINHO-INTER", "valor_rf_base"], 1080.0)
        self.assertEqual(pos.loc["PORQUINHO-INTER", "custo_total"], 1000.0)

        precos_fake = {"AAPL": (200.0, 1.5), "BTC-BRL": (600000.0, 2.0), "USDBRL=X": (5.0, 0.1)}
        cart, resumo = consolidar_carteira(df_ativos, df_ops, precos_yf=precos_fake)
        # AAPL = 1 * $200 * 5.0 = R$ 1000 | Porquinho = R$ 1080 | BTC = 0.01 * 600.000 = R$ 6000 -> Total = R$ 8080
        self.assertEqual(resumo["patrimonio_brl"], 8080.0)
        self.assertEqual(len(cart), 3)

        # Teste Frente 4: Rebalanceamento por novo aporte (R$ 1.920 -> patrimônio final R$ 10.000)
        # Metas: EUA 50% (R$ 5.000, atual R$ 1.000), RF 30% (R$ 3.000, atual R$ 1.080), BTC 20% (R$ 2.000, atual R$ 6.000 - já acima!)
        metas = {"Ações/ETFs EUA": 50.0, "Renda Fixa (BRL)": 30.0, "Cripto (BTC)": 20.0}
        df_reb = calcular_rebalanceamento(cart, metas, valor_novo_aporte_brl=1920.0).set_index("classe")
        self.assertAlmostEqual(df_reb["aporte_recomendado_brl"].sum(), 1920.0, places=2)
        # BTC já está acima da meta (6000 > 2000), então recebe R$ 0 de aporte!
        self.assertEqual(df_reb.loc["Cripto (BTC)", "aporte_recomendado_brl"], 0.0)
        self.assertGreater(df_reb.loc["Ações/ETFs EUA", "aporte_recomendado_brl"], df_reb.loc["Renda Fixa (BRL)", "aporte_recomendado_brl"])

        # Teste Frente 4: Evolução mensal de aportes
        df_ev = calcular_evolucao_aportes_mensal(df_ops, patrimonio_atual_brl=8080.0, usd_brl=5.0)
        self.assertFalse(df_ev.empty)
        self.assertIn("capital_acumulado_brl", df_ev.columns)

    def test_parser_pdf_inter_us_pypdf2(self):
        from functions import tratar_nota_corretagem_us_inter

        pdfs = list((Path(__file__).resolve().parent.parent / "ResumoContaInvestimento").glob("Confirm_*.pdf"))
        for pdf_path in pdfs:
            with open(pdf_path, "rb") as fh:
                df_nota = tratar_nota_corretagem_us_inter(fh)
            self.assertFalse(df_nota.empty, f"Nenhuma operação extraída de {pdf_path.name}")
            self.assertTrue({"Trade Date", "Symbol", "Action", "Price", "Quantity"}.issubset(df_nota.columns))
            self.assertTrue((df_nota["Quantity"] > 0).all())
            self.assertTrue((df_nota["Price"] > 0).all())

    def test_parser_fatura_cartao_mercado_pago_pdf(self):
        from expense_flow import _extrair_fatura_mercado_pago_pdf

        texto_exemplo = """
        Felipe Christofaro Romani
        Emitida em: 30/05/2026
        Detalhes de consumo
        Movimentações na fatura
        01/05Pagamento da fatura de maio/2026 R$ 778,63
        Cartão Visa [************2735]
        30/04OCIMAR HAIR BARBEARIA R$ 90,00
        09/01MERCADOLIVRE*MERCADOLIVRE Parcela 5 de 12 R$ 49,15
        25/05 Crédito concedido R$ 19,90
        Parcele a fatura do seu Cartão de Crédito Mercado Pago
        """
        df = _extrair_fatura_mercado_pago_pdf(texto_exemplo, "fatura-cartao-mercado-pago-2026-05.pdf")
        self.assertEqual(len(df), 3)
        self.assertEqual(df.iloc[0]["Valor"], -90.0)
        # Parcela 5 de 12 alocada no mês da fatura (maio/2026)
        self.assertEqual(df.iloc[1]["Data"], date(2026, 5, 9))
        self.assertEqual(df.iloc[1]["Valor"], -49.15)
        # Crédito concedido positivo
        self.assertEqual(df.iloc[2]["Valor"], 19.90)


if __name__ == "__main__":
    unittest.main()
