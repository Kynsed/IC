"""Regressões adversariais derivadas dos defeitos reproduzidos na revisão."""
import unittest
from decimal import Decimal

from neurosimbolico import Config, Veredito, verificar_dados
from neurosimbolico.dom import parse_html, parse_source
from neurosimbolico.evidencias import EvidenceBase
from neurosimbolico.normalizacao import decimal_variants


def campo(relatorio, nome):
    return next(r for r in relatorio.registros[0].resultados if r.afirmacao.campo == nome)


class TestRegressoesP0(unittest.TestCase):
    def test_limites_lexicais_e_numericos(self):
        base = EvidenceBase(parse_source("Mariana tem 130 anos.", "text"))
        self.assertEqual(base.find_literal("Ana"), [])
        self.assertEqual(base.find_loose("Ana"), [])
        self.assertEqual(base.find_numeric({Decimal(30)}), [])
        rel = verificar_dados([{"nome": "Ana", "idade": 30}],
                              "<article><h2>Mariana</h2><p>Idade: 130</p></article>")
        self.assertFalse(any(rel.registros[0].sugestoes.values()))

    def test_nao_concatena_numeros(self):
        for valor in ("10 ou 20", "10 e 20", "R$ 10 USD", "1.23,45"):
            with self.subTest(valor=valor):
                self.assertEqual(decimal_variants(valor), set())

    def test_moeda_divergente_nao_recebe_suporte(self):
        rel = verificar_dados([{"nome": "Caneta", "preco": "USD 10"}],
                              "<article><h2>Caneta</h2><p>Preço: R$ 10</p></article>")
        self.assertEqual(campo(rel, "preco").regra, "NUM-UNIDADE-DIVERGENTE")

    def test_moeda_apos_o_numero(self):
        rel = verificar_dados([{"preco": "EUR 10"}], "Preço: 10 EUR")
        self.assertEqual(campo(rel, "preco").veredito, Veredito.SUPORTADA)

    def test_tabela_preserva_linhas_e_colunas(self):
        html = ("<table><tr><th>Nome</th><th>Idade</th></tr>"
                "<tr><td>Maria</td><td>30</td></tr>"
                "<tr><td>João</td><td>45</td></tr></table>")
        indice = parse_html(html)
        cells = [n for n in indice.nodes if n.tag == "td"]
        self.assertTrue(all(indice.nodes[n.parent].tag == "tr" for n in cells))
        self.assertEqual(len({n.parent for n in cells}), 2)
        correto = verificar_dados([{"nome": "Maria", "idade": 30}], html)
        trocado = verificar_dados([{"nome": "Maria", "idade": 45}], html)
        self.assertEqual(campo(correto, "idade").veredito, Veredito.SUPORTADA)
        self.assertEqual(campo(trocado, "idade").veredito, Veredito.ATRIBUICAO_INCORRETA)

    def test_tabela_com_fechamentos_omitidos(self):
        indice = parse_html("<table><tr><td><span>Maria<td>30<tr><td>João<td>45</table>")
        cells = [n for n in indice.nodes if n.tag == "td"]
        self.assertEqual(len({n.parent for n in cells}), 2)
        self.assertTrue(all(indice.nodes[n.parent].tag == "tr" for n in cells))

    def test_contexto_funciona_com_dois_campos(self):
        html = ("<article><h2>Maria</h2><p>Idade: 30</p></article>"
                "<article><h2>João</h2><p>Idade: 45</p></article>")
        rel = verificar_dados([{"nome": "Maria", "idade": 45}], html)
        self.assertEqual(campo(rel, "idade").veredito, Veredito.ATRIBUICAO_INCORRETA)
        self.assertEqual([s.valor for s in rel.registros[0].sugestoes["r0:idade"]], ["30"])

    def test_mesma_entidade_outro_atributo(self):
        html = "<article><h2>Maria</h2><p>Idade: 30</p><p>Casa: 45</p></article>"
        rel = verificar_dados([{"nome": "Maria", "idade": 45}], html)
        self.assertEqual(campo(rel, "idade").regra, "CTX-OUTRO-ATRIBUTO")
        self.assertEqual([s.valor for s in rel.registros[0].sugestoes["r0:idade"]], ["30"])

    def test_todas_ocorrencias_participam_do_julgamento(self):
        html = "".join(f"<article id='p{i}'><h2>Livro {i}</h2><p>Autor: Maria</p></article>"
                       for i in range(60))
        rel = verificar_dados([{"titulo": "Livro 59", "autor": "Maria"}], html)
        autor = campo(rel, "autor")
        self.assertEqual(autor.veredito, Veredito.SUPORTADA)
        self.assertIn("p59", autor.evidencia_principal.path)
        self.assertEqual(autor.to_dict()["total_evidencias"], 60)
        self.assertEqual(len(autor.to_dict()["evidencias"]), 3)

    def test_sem_reparo_com_ancora_de_um_unico_chunk(self):
        html = ("<article><h2>Maria</h2></article>"
                "<article><h2>João</h2><p>Idade: 45</p></article>")
        rel = verificar_dados([{"nome": "Maria", "idade": 99}], html)
        self.assertEqual(rel.registros[0].sugestoes["r0:idade"], [])

    def test_identidade_inexistente_nao_empresta_campos(self):
        html = "<article><h2>João</h2><p>Idade: 45</p></article>"
        rel = verificar_dados([{"nome": "Pedro", "idade": 45}], html)
        self.assertEqual(campo(rel, "idade").veredito, Veredito.PARCIAL)
        self.assertFalse(any(rel.registros[0].sugestoes.values()))

    def test_identidades_repetidas_sao_ambiguas(self):
        html = ("<article><h2>Maria</h2><p>Idade: 30</p></article>"
                "<article><h2>Maria</h2><p>Idade: 45</p></article>")
        rel = verificar_dados([{"nome": "Maria", "idade": 30}], html)
        self.assertEqual(campo(rel, "idade").veredito, Veredito.PARCIAL)
        self.assertFalse(rel.registros[0].coesao.aplicavel)

    def test_texto_rotulado_preserva_entidade(self):
        fonte = "Nome: Maria\nIdade: 30\nNome: João\nIdade: 45"
        rel = verificar_dados([{"nome": "Maria", "idade": 45}], fonte)
        self.assertEqual(campo(rel, "idade").regra, "CTX-OUTRA-ENTIDADE")
        self.assertEqual([s.valor for s in rel.registros[0].sugestoes["r0:idade"]], ["30"])

    def test_texto_sem_rotulos_mantem_incerteza(self):
        rel = verificar_dados([{"nome": "Maria", "idade": 45}], "Maria\n30\nJoão\n45")
        self.assertEqual(campo(rel, "idade").veredito, Veredito.PARCIAL)

    def test_literal_sob_negacao_nao_e_suporte(self):
        rel = verificar_dados([{"nome": "Produto A", "status": "disponível"}],
                              "<article><h2>Produto A</h2><p>Status: não disponível</p></article>")
        self.assertNotEqual(campo(rel, "status").veredito, Veredito.SUPORTADA)

    def test_cobertura_de_tokens_nao_comprova_relacoes(self):
        fonte = "Maria não mora em Lisboa e trabalha em uma empresa pequena no centro da cidade."
        rel = verificar_dados([{"descricao": "Maria mora em Lisboa e trabalha em uma empresa pequena no centro da cidade."}], fonte)
        self.assertEqual(campo(rel, "descricao").veredito, Veredito.PARCIAL)

    def test_fuzzy_nao_comprova_fato(self):
        rel = verificar_dados([{"nome": "Mariana Silva"}], "<article><h2>Mariana Silve</h2></article>")
        self.assertNotEqual(campo(rel, "nome").veredito, Veredito.SUPORTADA)

    def test_reparo_nao_desempata_valores_conflitantes(self):
        html = "<article><h2>Maria</h2><p>Idade: 30</p><p>Idade: 31</p></article>"
        rel = verificar_dados([{"nome": "Maria", "idade": 99}], html)
        self.assertEqual(rel.registros[0].sugestoes["r0:idade"], [])

    def test_ano_usa_data_de_referencia_registrada(self):
        rel = verificar_dados([{"ano": 2030}], "Ano: 2030",
                              config=Config(data_referencia="2020-01-01"))
        self.assertEqual(campo(rel, "ano").regra, "SIM-ANO-INTERVALO")


if __name__ == "__main__":
    unittest.main()
