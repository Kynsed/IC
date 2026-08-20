"""Testes da camada de normalização determinística."""

import unittest
from datetime import date
from decimal import Decimal

from neurosimbolico.normalizacao import (
    clean_whitespace,
    content_tokens,
    decimal_variants,
    ean_valid,
    fold,
    is_abstention,
    isbn_valid,
    iter_numbers,
    looks_like_html,
    normalize,
    parse_date,
    parse_decimal,
)


class TestFold(unittest.TestCase):
    def test_preserva_comprimento(self):
        """Requisito central: offsets do texto normalizado batem com o original."""
        for amostra in ["Ação", "PREÇO: R$ 1.234,56", "Máquina ÀÉÎÕÜ ç",
                        "Straße", "ﬁm", "½ litro", "İstanbul", "日本語"]:
            self.assertEqual(len(fold(amostra)), len(amostra), amostra)

    def test_remove_acentos_e_caixa(self):
        self.assertEqual(fold("Publicação ÁÉÍÓÚ"), "publicacao aeiou")

    def test_espacos_especiais(self):
        self.assertEqual(clean_whitespace("R$\xa0 69,69\n\n"), "R$ 69,69")

    def test_tokens_de_conteudo_sem_stopwords(self):
        tokens = content_tokens("A obra narra a história de Bentinho")
        self.assertNotIn("a", tokens)
        self.assertNotIn("de", tokens)
        self.assertIn("bentinho", tokens)


class TestNumeros(unittest.TestCase):
    def test_moeda_brasileira(self):
        self.assertEqual(parse_decimal("R$ 1.234,56"), Decimal("1234.56"))
        self.assertEqual(parse_decimal("R$ 69,69"), Decimal("69.69"))

    def test_formato_americano(self):
        self.assertEqual(parse_decimal("$1,234.56"), Decimal("1234.56"))

    def test_ambiguidade_gera_duas_leituras(self):
        """'1.234' é 1234 (pt-BR) ou 1.234 (en-US); ambas ficam disponíveis."""
        self.assertEqual(decimal_variants("1.234"), {Decimal("1234"), Decimal("1.234")})

    def test_inteiro_simples(self):
        self.assertEqual(parse_decimal("400"), Decimal("400"))

    def test_varredura_detecta_simbolo_monetario(self):
        ocorrencias = list(iter_numbers(normalize("preço r$ 69,69 e 400 páginas")))
        valores = [o.raw for o in ocorrencias]
        self.assertIn("69,69", valores)
        self.assertIn("400", valores)
        self.assertTrue(ocorrencias[0].currency)
        self.assertFalse(ocorrencias[1].currency)

    def test_offsets_apontam_para_o_texto(self):
        texto = normalize("valor total: 1.234,56 reais")
        ocorrencia = next(iter_numbers(texto))
        self.assertEqual(texto[ocorrencia.start:ocorrencia.end], "1.234,56")


class TestIdentificadores(unittest.TestCase):
    def test_isbn13_valido(self):
        self.assertTrue(isbn_valid("9788582850350"))
        self.assertTrue(isbn_valid("978-85-8285-035-0"))

    def test_isbn13_invalido(self):
        self.assertFalse(isbn_valid("9788582850351"))

    def test_isbn10(self):
        self.assertTrue(isbn_valid("0306406152"))
        self.assertFalse(isbn_valid("0306406153"))

    def test_forma_nao_reconhecida_retorna_none(self):
        """Distinguir 'inválido' de 'não verificável' evita falso positivo."""
        self.assertIsNone(isbn_valid("12345"))
        self.assertIsNone(ean_valid("abc"))

    def test_ean13(self):
        self.assertTrue(ean_valid("7891000315507"))


class TestDatas(unittest.TestCase):
    def test_formatos_numericos(self):
        self.assertEqual(parse_date("15/03/2019"), date(2019, 3, 15))
        self.assertEqual(parse_date("2019-03-15"), date(2019, 3, 15))

    def test_por_extenso(self):
        self.assertEqual(parse_date("15 de março de 2019"), date(2019, 3, 15))
        self.assertEqual(parse_date("March 15, 2019"), date(2019, 3, 15))

    def test_invalida(self):
        self.assertIsNone(parse_date("não disponível"))
        self.assertIsNone(parse_date("32/13/2019"))


class TestClassificacao(unittest.TestCase):
    def test_deteccao_de_html(self):
        self.assertTrue(looks_like_html("<html><body><div>a</div>" + "<p>x</p>" * 5))
        self.assertFalse(looks_like_html("Dom Casmurro\nAutor\nASSIS, MACHADO DE"))

    def test_abstencao(self):
        for valor in ["Não disponível", "n/a", "", "NAO INFORMADO", None]:
            self.assertTrue(is_abstention(valor), valor)
        self.assertFalse(is_abstention("R$ 69,69"))


if __name__ == "__main__":
    unittest.main()
