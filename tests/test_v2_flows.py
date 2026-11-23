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

    def test_exportar_yahoo_financas_e_iof_ir(self):
        from core.portfolio import calcular_ir_iof_renda_fixa, exportar_yahoo_financas

        df_a = pd.DataFrame(
            [
                {
                    "id": "a_brk",
                    "ticker": "BRK.B",
                    "nome": "Berkshire",
                    "classe": "acao_us",
                    "moeda": "USD",
                    "conta": "Inter US",
                    "fonte_cotacao": "yfinance",
                    "codigo_cotacao": "BRK-B",
                    "ativo": "S",
                },
                {
                    "id": "a_btc",
                    "ticker": "BTC",
                    "nome": "Bitcoin",
                    "classe": "cripto",
                    "moeda": "BRL",
                    "conta": "Binance",
                    "fonte_cotacao": "yfinance",
                    "codigo_cotacao": "BTC-BRL",
                    "ativo": "S",
                },
                {
                    "id": "a_rf",
                    "ticker": "CDB-ML-FEV27",
                    "nome": "CDB ML",
                    "classe": "renda_fixa",
                    "moeda": "BRL",
                    "conta": "Mercado Pago",
                    "fonte_cotacao": "cdi",
                    "codigo_cotacao": "CDI",
                    "ativo": "S",
                },
            ]
        )
        df_o = pd.DataFrame(
            [
                {"id": "1", "data": "2026-11-10", "ativo_id": "a_brk", "conta": "Inter US", "tipo": "compra", "quantidade": 2.0, "preco": 500.0, "taxas": 0.0, "valor_total": 1000.0, "moeda": "USD", "criado_em": "2026-11-10T10:00:00"},
                {"id": "2", "data": "2026-11-15", "ativo_id": "a_brk", "conta": "Inter US", "tipo": "venda", "quantidade": 0.5, "preco": 520.0, "taxas": 0.0, "valor_total": 260.0, "moeda": "USD", "criado_em": "2026-11-15T10:00:00"},
                {"id": "3", "data": "2026-11-18", "ativo_id": "a_rf", "conta": "Mercado Pago", "tipo": "aporte", "quantidade": 1.0, "preco": 10000.0, "taxas": 0.0, "valor_total": 10000.0, "moeda": "BRL", "criado_em": "2026-11-18T10:00:00"},
                {"id": "4", "data": "2026-11-22", "ativo_id": "a_btc", "conta": "Binance", "tipo": "compra", "quantidade": 0.1, "preco": 500000.0, "taxas": 0.0, "valor_total": 50000.0, "moeda": "BRL", "criado_em": "2026-11-22T10:00:00"},
            ]
        )

        # Histórico completo: 2 linhas de BRK-B (RF excluída), venda negativa
        df_hist, csv_hist = exportar_yahoo_financas(df_a, df_o, apenas_abertas=False)
        self.assertEqual(list(df_hist.columns), ["Symbol", "Trade Date", "Purchase Price", "Quantity"])
        self.assertEqual(len(df_hist), 2)
        self.assertEqual(df_hist.iloc[0]["Symbol"], "BRK-B")
        self.assertEqual(df_hist.iloc[0]["Trade Date"], "2026-11-10")
        self.assertEqual(df_hist.iloc[1]["Quantity"], -0.5)
        self.assertIn(b"Symbol,Trade Date,Purchase Price,Quantity", csv_hist)

        # Lotes FIFO: consome 0.5 da compra de 2.0, sobra 1.5 com data/preço originais (2026-11-10, 500.0)
        df_fifo, _ = exportar_yahoo_financas(df_a, df_o, modo="lotes_fifo")
        self.assertEqual(len(df_fifo), 1)
        self.assertEqual(df_fifo.iloc[0]["Symbol"], "BRK-B")
        self.assertEqual(df_fifo.iloc[0]["Trade Date"], "2026-11-10")
        self.assertEqual(df_fifo.iloc[0]["Quantity"], 1.5)
        self.assertEqual(df_fifo.iloc[0]["Purchase Price"], 500.0)

        # Posições abertas com Cripto: BRK-B + BTC-USD convertido para USD
        df_ab, _ = exportar_yahoo_financas(
            df_a, df_o, apenas_abertas=True, incluir_cripto=True, usd_brl=5.0, data_ref=date(2026, 11, 22)
        )
        self.assertEqual(len(df_ab), 2)
        self.assertEqual(set(df_ab["Symbol"]), {"BRK-B", "BTC-USD"})
        btc_row = df_ab[df_ab["Symbol"] == "BTC-USD"].iloc[0]
        self.assertEqual(btc_row["Purchase Price"], 100000.0)

        # IOF dia 4 = 86%, IR = 22.5% (bate com print CDB Mercado Livre)
        trib = calcular_ir_iof_renda_fixa("2026-11-18", rendimento_bruto=13.21, data_ref=date(2026, 11, 22))
        self.assertEqual(trib["dias_corridos"], 4)
        self.assertEqual(trib["aliquota_iof_pct"], 86.0)
        self.assertEqual(trib["aliquota_ir_pct"], 22.5)
        self.assertEqual(trib["iof_estimado"], 11.36)
        self.assertEqual(trib["ir_estimado"], 0.42)
        self.assertEqual(trib["rendimento_liquido"], 1.43)

    def test_advisor_memoria_e_tool_calling(self):
        from langchain_core.messages import AIMessage
        from core.advisor import (
            CHAVE_MEMORIA_PERFIL,
            carregar_memoria_lista,
            criar_ferramentas_consultor,
            executar_turno_consultor,
            formatar_system_prompt,
        )

        cfg_mem: dict[str, str] = {}

        def ler_aba_fake(nome: str) -> pd.DataFrame:
            if nome == "metas":
                return pd.DataFrame([{"nome": "Reserva", "valor_atual": 28000.0, "valor_alvo": 30000.0}])
            return pd.DataFrame()

        tools = criar_ferramentas_consultor(
            leitor_aba=ler_aba_fake,
            leitor_config=lambda: dict(cfg_mem),
            gravador_config=lambda d: cfg_mem.update(d),
        )

        class FakeLLM:
            def __init__(self):
                self.passo = 0

            def bind_tools(self, _tools):
                return self

            def invoke(self, _msgs):
                self.passo += 1
                if self.passo == 1:
                    return AIMessage(
                        content="",
                        tool_calls=[
                            {"id": "t1", "name": "salvar_memoria_usuario", "args": {"fato": "Foco em ETFs VOO e QQQM"}},
                            {"id": "t2", "name": "consultar_metas_e_reserva", "args": {}},
                        ],
                    )
                return AIMessage(content="Anotei seu foco em VOO/QQQM e vi que sua Reserva está em R$ 28.000 de R$ 30.000.")

        resp, usadas = executar_turno_consultor(
            llm=FakeLLM(),
            tools=tools,
            cfg=cfg_mem,
            historico_mensagens=[],
            pergunta="Guarde que meu foco é VOO e QQQM e veja minha reserva",
        )
        self.assertEqual(usadas, ["salvar_memoria_usuario", "consultar_metas_e_reserva"])
        self.assertIn("28.000", resp)
        self.assertEqual(carregar_memoria_lista(cfg_mem), ["Foco em ETFs VOO e QQQM"])
        self.assertIn("Foco em ETFs VOO e QQQM", formatar_system_prompt(cfg_mem))

    def test_selic_e_projecao_rf(self):
        from unittest.mock import MagicMock, patch
        from core.portfolio import buscar_selic_atual, projetar_rendimento_rf

        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"data": "09/12/2026", "valor": "13.75"}]
        mock_resp.raise_for_status.return_value = None

        with patch("requests.get", return_value=mock_resp):
            selic, cdi, dt = buscar_selic_atual()
        self.assertEqual(selic, 13.75)
        self.assertEqual(cdi, 13.65)
        self.assertEqual(dt, "09/12/2026")

        proj = projetar_rendimento_rf(10000.0, 120.0, 13.65)
        self.assertEqual(proj["taxa_efetiva_aa"], 16.38)
        self.assertGreater(proj["rendimento_mensal_bruto"], 120.0)

    def test_holerite_parser_e_resumo(self):
        from core.holerite import parse_holerite_texto, resumir_holerites

        ocr = """
        MERCADOPAGO.COM REP. LTDA CNPJ: 10.573.521/0001-91
        SALARIO
        11.660,00
        0010 Salário 14,00 5.441,33
        0830 Ajuda de Custo Escritorio 200,00
        /314 Contr. INSS Remuneração 14,00 988,07
        /401 Tributo IRRF 27,50 97,08
        /505 Vale-refeição empregado 86,40
        /B02 Adiantamento pago 2.176,53
        5300 Assistência Médica 100,00
        9012 Convênio Odontológico 32,77
        9FPH PrevPriv PGBL 2 466,40
        9VA1 Vale Alimentação Empregad 36,75
        MES: Outubro ANO: 2026
        Base IRRF: 4795.29 Base INSS: 13732.88
        TOTAL DE PROVENTOS 14.741,31
        TOTAL DE DESCONTOS 12.275,55
        Base FGTS: 19562.88 FGTS: 1565.03
        TOTAL LÍQUIDO 2.465,76
        """
        reg = parse_holerite_texto(ocr)
        self.assertEqual(reg["competencia"], "2026-10")
        self.assertEqual(reg["salario_base"], 11660.0)
        self.assertEqual(reg["total_proventos"], 14741.31)
        self.assertEqual(reg["total_liquido"], 2465.76)
        self.assertEqual(reg["inss"], 988.07)
        self.assertEqual(reg["irrf"], 97.08)
        self.assertEqual(reg["fgts"], 1565.03)
        self.assertEqual(reg["pgbl"], 466.40)
        self.assertEqual(reg["ajuda_custo"], 200.0)
        self.assertEqual(reg["adiantamento"], 2176.53)
        self.assertAlmostEqual(reg["beneficios_desconto"], 255.92, places=2)

        res = resumir_holerites(pd.DataFrame([reg]))
        self.assertEqual(res["meses"], 1)
        self.assertEqual(res["total_fgts"], 1565.03)
        self.assertEqual(res["total_pgbl_empresa"], 466.40)
        self.assertEqual(res["total_pgbl_geral"], 932.80)
        self.assertGreater(res["margem_pgbl_restante"], 1000.0)


if __name__ == "__main__":
    unittest.main()
