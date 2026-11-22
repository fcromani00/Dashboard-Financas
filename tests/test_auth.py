import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.auth import gerar_hash_senha, verificar_hash_senha  # noqa: E402


class TestAuthV2(unittest.TestCase):
    def test_hash_e_verificacao_pbkdf2(self):
        h = gerar_hash_senha("MinhaSenhaForte123")
        self.assertTrue(h.startswith("pbkdf2_sha256$"))
        self.assertTrue(verificar_hash_senha("MinhaSenhaForte123", h))
        self.assertFalse(verificar_hash_senha("minhasenhaforte123", h))
        self.assertFalse(verificar_hash_senha("", h))
        self.assertFalse(verificar_hash_senha("MinhaSenhaForte123", "hash_invalido"))

    def test_salts_diferentes_para_mesma_senha(self):
        h1 = gerar_hash_senha("1234")
        h2 = gerar_hash_senha("1234")
        self.assertNotEqual(h1, h2)
        self.assertTrue(verificar_hash_senha("1234", h1))
        self.assertTrue(verificar_hash_senha("1234", h2))


if __name__ == "__main__":
    unittest.main()
