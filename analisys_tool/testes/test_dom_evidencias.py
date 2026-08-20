"""Testes do indexador de DOM (stdlib) e da base de evidências."""

import unittest
from decimal import Decimal

from neurosimbolico.dom import parse_html, parse_source, parse_text
from neurosimbolico.evidencias import EvidenceBase

HTML = """<!DOCTYPE html>
<html><head><title>Catálogo</title><style>.a{color:red}</style></head>
<body>
  <article id="p1" class="produto">
    <h1>Dom Casmurro</h1>
    <ul>
      <li><strong>Editora:</strong> PENGUIN COMPANHIA</li>
      <li><strong>ISBN:</strong> 978-85-8285-035-0
      <li><strong>Páginas:</strong> 400</li>
    </ul>
    <p class="preco">R$ 69,69</p>
    <meta itemprop="price" content="69.69">
    <img src="capa.jpg" alt="Capa de Dom Casmurro">
  </article>
  <article id="p2" class="produto">
    <h1>Quincas Borba</h1>
    <p class="preco">R$ 54,90</p>
  </article>
  <script>var preco = 999.99;</script>
</body></html>"""


class TestParserHtml(unittest.TestCase):
    def setUp(self):
        self.indice = parse_html(HTML)

    def test_arvore_construida(self):
        self.assertTrue(self.indice.structural)
        tags = {n.tag for n in self.indice.nodes}
        self.assertIn("article", tags)
        self.assertIn("strong", tags)

    def test_ignora_conteudo_de_script_e_style(self):
        textos = " ".join(c.text for c in self.indice.chunks)
        self.assertNotIn("999.99", textos)
        self.assertNotIn("color:red", textos)

    def test_li_sem_fechamento_nao_aninha(self):
        """Tolerância a marcação malformada: <li> abre implicitamente fecha o anterior."""
        itens = [n for n in self.indice.nodes if n.tag == "li"]
        self.assertEqual(len(itens), 3)
        for item in itens:
            self.assertEqual(self.indice.nodes[item.parent].tag, "ul")

    def test_atributos_de_conteudo_viram_evidencia(self):
        tipos = {c.kind for c in self.indice.chunks}
        self.assertIn("attr:content", tipos)
        self.assertIn("attr:alt", tipos)

    def test_caminho_legivel_e_ancestralidade(self):
        alvo = next(c for c in self.indice.chunks if c.text == "PENGUIN COMPANHIA")
        self.assertIn("article#p1.produto", alvo.path)
        ancestrais = {self.indice.nodes[a].tag for a in self.indice.ancestors(alvo.node)}
        self.assertIn("article", ancestrais)

    def test_subarvore_isola_o_produto(self):
        p2 = next(n for n in self.indice.nodes if n.attrs.get("id") == "p2")
        texto = self.indice.text_of_subtree(p2.index)
        self.assertIn("Quincas Borba", texto)
        self.assertNotIn("Dom Casmurro", texto)


class TestDeteccaoDeFonte(unittest.TestCase):
    def test_texto_limpo_vira_indice_linear(self):
        indice = parse_source("Dom Casmurro\nR$ 69,69\nEditora: PENGUIN")
        self.assertEqual(indice.kind, "text")
        self.assertFalse(indice.structural)
        self.assertEqual(len(indice.chunks), 3)

    def test_html_detectado_automaticamente(self):
        self.assertEqual(parse_source(HTML).kind, "html")

    def test_forcar_tipo(self):
        self.assertEqual(parse_source(HTML, "text").kind, "text")


class TestBaseDeEvidencias(unittest.TestCase):
    def setUp(self):
        self.base = EvidenceBase(parse_html(HTML))

    def test_casamento_literal_rastreia_ate_a_fonte(self):
        achados = self.base.find_literal("PENGUIN COMPANHIA")
        self.assertTrue(achados)
        self.assertEqual(achados[0].snippet_match, "PENGUIN COMPANHIA")
        self.assertIn("article#p1", achados[0].path)

    def test_casamento_tolerante_a_separadores(self):
        self.assertTrue(self.base.find_loose("9788582850350"))

    def test_equivalencia_numerica_entre_formatos(self):
        """'R$ 69,69' na página deve casar com o mesmo valor decimal."""
        achados = self.base.find_numeric({Decimal("69.69")})
        self.assertTrue(achados)

    def test_proximidade_de_rotulo(self):
        achado = self.base.find_numeric({Decimal("400")})[0]
        self.assertIsNotNone(
            self.base.label_near(achado.flow_start, achado.flow_end, ["Páginas"]))
        self.assertIsNone(
            self.base.label_near(achado.flow_start, achado.flow_end, ["Avaliação"]))

    def test_numeros_novos_detectados(self):
        self.assertEqual(self.base.novel_numbers("custa R$ 69,69"), [])
        self.assertIn("1234", self.base.novel_numbers("edição de 1234 exemplares"))

    def test_cobertura_e_janela(self):
        cobertura, faltantes = self.base.coverage("Dom Casmurro PENGUIN")
        self.assertEqual(cobertura, 1.0)
        self.assertEqual(faltantes, [])
        cobertura, faltantes = self.base.coverage("Dom Casmurro Sputnik")
        self.assertLess(cobertura, 1.0)
        self.assertIn("sputnik", faltantes)

    def test_valor_ausente_nao_produz_casamento(self):
        self.assertEqual(self.base.find_literal("EDITORA ÁTICA"), [])


if __name__ == "__main__":
    unittest.main()
