import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.recurring import analisar_parcelas, detectar_recorrencias, extrair_info_parcela  # noqa: E402


class TestRecurringV2(unittest.TestCase):
    def test_extrair_info_parcela_sem_falso_positivo_em_data(self):
        # Padrão Banco Inter na coluna observacao
        self.assertEqual(extrair_info_parcela("LOJAS YOUCOM SAO PAULO", "Parcela 2/5"), (2, 5))
        # Padrão Nubank na descrição
        self.assertEqual(extrair_info_parcela("Amazon Br - Parcela 3/10", ""), (3, 10))
        self.assertEqual(extrair_info_parcela("Mercado Livre 1/4", ""), (1, 4))
        # Data DD/MM/YYYY NÃO deve ser confundida com parcela
        self.assertIsNone(extrair_info_parcela('Credito B3: "NOTA NEGOCIACAO BOV * 19/09/2025"', ""))
        self.assertIsNone(extrair_info_parcela("Compra normal à vista", "Compra à vista"))

    def test_projecao_parcelas_futuras(self):
        df = pd.DataFrame(
            [
                {
                    "id": "1",
                    "data": date(2026, 4, 15),
                    "valor": -100.0,
                    "descricao": "LOJAS YOUCOM",
                    "categoria": "Vestuário",
                    "conta": "Inter",
                    "transferencia": "N",
                    "observacao": "Parcela 1/4",
                },
                {
                    "id": "2",
                    "data": date(2026, 5, 15),
                    "valor": -100.0,
                    "descricao": "LOJAS YOUCOM",
                    "categoria": "Vestuário",
                    "conta": "Inter",
                    "transferencia": "N",
                    "observacao": "Parcela 2/4",
                },
            ]
        )
        res = analisar_parcelas(df, mes_referencia="2026-05")
        self.assertEqual(res["total_mes"], 100.0)
        # Faltam as parcelas 3/4 (2026-06) e 4/4 (2026-07) -> R$ 200,00 futuros
        self.assertEqual(res["total_futuro"], 200.0)
        self.assertEqual(res["projecao_futura"]["ano_mes"].tolist(), ["2026-06", "2026-07"])
        self.assertEqual(res["parcelas_ativas"].iloc[0]["parcelas_restantes"], 2)

    def test_detectar_recorrencias_fixos_e_habitos(self):
        df = pd.DataFrame(
            [
                # Assinatura mensal fixa (1x por mês, valor igual)
                {"id": "1", "data": date(2026, 1, 10), "valor": -55.90, "descricao": "Netflix.Com", "categoria": "Assinaturas", "conta": "Nubank", "transferencia": "N", "observacao": ""},
                {"id": "2", "data": date(2026, 2, 10), "valor": -55.90, "descricao": "Netflix.Com", "categoria": "Assinaturas", "conta": "Nubank", "transferencia": "N", "observacao": ""},
                {"id": "3", "data": date(2026, 3, 10), "valor": -55.90, "descricao": "Netflix.Com", "categoria": "Assinaturas", "conta": "Nubank", "transferencia": "N", "observacao": ""},
                # Hábito frequente (múltiplas vezes por mês)
                {"id": "4", "data": date(2026, 1, 5), "valor": -20.0, "descricao": "Uber *Trip", "categoria": "Transporte", "conta": "Nubank", "transferencia": "N", "observacao": ""},
                {"id": "5", "data": date(2026, 1, 12), "valor": -30.0, "descricao": "Uber *Trip", "categoria": "Transporte", "conta": "Nubank", "transferencia": "N", "observacao": ""},
                {"id": "6", "data": date(2026, 2, 8), "valor": -25.0, "descricao": "Uber *Trip", "categoria": "Transporte", "conta": "Nubank", "transferencia": "N", "observacao": ""},
                {"id": "7", "data": date(2026, 2, 19), "valor": -45.0, "descricao": "Uber *Trip", "categoria": "Transporte", "conta": "Nubank", "transferencia": "N", "observacao": ""},
                {"id": "8", "data": date(2026, 3, 4), "valor": -18.0, "descricao": "Uber *Trip", "categoria": "Transporte", "conta": "Nubank", "transferencia": "N", "observacao": ""},
                {"id": "9", "data": date(2026, 3, 21), "valor": -42.0, "descricao": "Uber *Trip", "categoria": "Transporte", "conta": "Nubank", "transferencia": "N", "observacao": ""},
            ]
        )
        rec = detectar_recorrencias(df, min_meses=3)
        self.assertEqual(len(rec["fixos"]), 1)
        self.assertEqual(rec["fixos"].iloc[0]["media_mensal"], 55.90)
        self.assertEqual(rec["total_fixos_ativos_mes"], 55.90)
        self.assertEqual(len(rec["habitos"]), 1)
        self.assertEqual(rec["habitos"].iloc[0]["media_mensal"], 60.0)


if __name__ == "__main__":
    unittest.main()
