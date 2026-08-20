"""Testes de ponta a ponta do pipeline de verificação."""

import json
import unittest
from pathlib import Path

from neurosimbolico import Config, Veredito, verificar, verificar_dados
from neurosimbolico.relatorio import gerar_html

RAIZ = Path(__file__).resolve().parent.parent
EXEMPLOS = RAIZ / "exemplos"

PAGINA = """<html><body>
<article id="p1">
  <h1>Dom Casmurro</h1>
  <p>ASSIS, MACHADO DE</p>
  <ul><li>Editora: PENGUIN COMPANHIA</li>
      <li>ISBN: 9788582850350</li>
      <li>Número de Páginas: 400</li>
      <li>Ano de Publicação: 2019</li></ul>
  <p class="preco">R$ 69,69</p>
  <p class="descricao">Publicado em 1899, Dom Casmurro narra a história de Bentinho.</p>
</article>
<article id="p2">
  <h1>Quincas Borba</h1>
  <p>ASSIS, MACHADO DE</p>
  <ul><li>Editora: COMPANHIA DAS LETRAS</li>
      <li>Número de Páginas: 320</li></ul>
  <p class="preco">R$ 54,90</p>
</article>
</body></html>"""


def _verificar(registros, pagina=PAGINA, **kwargs):
    return verificar_dados(registros, pagina, **kwargs)


def _campo(relatorio, indice, campo):
    bloco = relatorio.registros[indice]
    return next(r for r in bloco.resultados if r.afirmacao.campo == campo)


class TestVereditos(unittest.TestCase):
    def test_valor_presente_na_pagina(self):
        rel = _verificar([{"Título": "Dom Casmurro"}])
        self.assertEqual(_campo(rel, 0, "Título").veredito, Veredito.SUPORTADA)

    def test_valor_ausente_e_alucinacao(self):
        rel = _verificar([{"Editora": "EDITORA ÁTICA"}])
        resultado = _campo(rel, 0, "Editora")
        self.assertEqual(resultado.veredito, Veredito.NAO_SUPORTADA)
        self.assertTrue(resultado.alucinacao)

    def test_preco_equivalente_em_outro_formato(self):
        rel = _verificar([{"Preço": "69,69"}])
        self.assertEqual(_campo(rel, 0, "Preço").veredito, Veredito.SUPORTADA)

    def test_preco_inexistente(self):
        rel = _verificar([{"Preço": "R$ 29,90"}])
        self.assertEqual(_campo(rel, 0, "Preço").veredito, Veredito.NAO_SUPORTADA)

    def test_isbn_fabricado_reprovado_pelo_digito_verificador(self):
        rel = _verificar([{"ISBN": "9788582850351"}])
        resultado = _campo(rel, 0, "ISBN")
        self.assertEqual(resultado.veredito, Veredito.INVALIDA)
        self.assertEqual(resultado.regra, "SIM-CHECKSUM")

    def test_isbn_bem_formado_porem_ausente(self):
        """Checksum válido não é ancoragem: o valor precisa estar na página."""
        rel = _verificar([{"ISBN": "9788526015678"}])
        self.assertEqual(_campo(rel, 0, "ISBN").veredito, Veredito.NAO_SUPORTADA)

    def test_ano_implausivel(self):
        rel = _verificar([{"Ano de Publicação": "2035"}])
        resultado = _campo(rel, 0, "Ano de Publicação")
        self.assertEqual(resultado.veredito, Veredito.INVALIDA)
        self.assertEqual(resultado.regra, "SIM-ANO-INTERVALO")

    def test_abstencao_nao_conta_como_alucinacao(self):
        rel = _verificar([{"Editora": "Não disponível"}])
        resultado = _campo(rel, 0, "Editora")
        self.assertEqual(resultado.veredito, Veredito.ABSTENCAO)
        self.assertFalse(resultado.alucinacao)

    def test_erro_da_ferramenta_e_distinguido(self):
        rel = _verificar([{"Editora": "Erro na API"}])
        self.assertEqual(_campo(rel, 0, "Editora").veredito, Veredito.ERRO_EXTRACAO)

    def test_evidencia_sempre_acompanha_o_suporte(self):
        rel = _verificar([{"Título": "Dom Casmurro", "Preço": "R$ 69,69"}])
        for campo in ("Título", "Preço"):
            resultado = _campo(rel, 0, campo)
            self.assertIsNotNone(resultado.evidencia_principal)
            self.assertTrue(resultado.evidencia_principal.path)


class TestLocalidadeNoDom(unittest.TestCase):
    """A família de erro descrita na documentação: valor certo, item errado."""

    REGISTRO_MISTURADO = {
        "Título": "Quincas Borba",
        "Autor": "ASSIS, MACHADO DE",
        "Editora": "PENGUIN COMPANHIA",       # pertence ao produto 1
        "Número de Páginas": "320",
        "Preço": "R$ 54,90",
    }

    def test_campo_de_outro_item_e_detectado(self):
        rel = _verificar([self.REGISTRO_MISTURADO])
        resultado = _campo(rel, 0, "Editora")
        self.assertEqual(resultado.veredito, Veredito.ATRIBUICAO_INCORRETA)
        self.assertEqual(resultado.regra, "DOM-FORA-DA-ANCORA")

    def test_ancora_e_a_subarvore_do_item(self):
        rel = _verificar([self.REGISTRO_MISTURADO])
        self.assertIn("p2", rel.registros[0].coesao.caminho_ancora)
        self.assertEqual(rel.registros[0].coesao.campos_fora, ["Editora"])

    def test_valor_repetido_e_reancorado_no_item_correto(self):
        """O autor aparece nos dois produtos: não pode ser acusado de troca."""
        rel = _verificar([self.REGISTRO_MISTURADO])
        resultado = _campo(rel, 0, "Autor")
        self.assertEqual(resultado.veredito, Veredito.SUPORTADA)
        self.assertIn("p2", resultado.evidencia_principal.path)

    def test_registro_coeso_nao_dispara_a_regra(self):
        rel = _verificar([{
            "Título": "Dom Casmurro", "Editora": "PENGUIN COMPANHIA",
            "Número de Páginas": "400", "Preço": "R$ 69,69",
        }])
        self.assertEqual(rel.registros[0].coesao.campos_fora, [])
        restricao = next(r for r in rel.registros[0].restricoes if r.id == "R-COESAO-DOM")
        self.assertFalse(restricao.violada)

    def test_evidencia_em_head_nao_e_atribuicao_incorreta(self):
        """
        Regressão de falso positivo observado em página real (BDTA/USP): o
        título casava primeiro com <meta> no <head>, fora da subárvore do item,
        e era acusado de vir de outro produto. Metadado de página não é item.
        """
        pagina = """<html>
        <head><meta name="citation_title" content="Guia Completo de Jardinagem"></head>
        <body><article id="p1">
          <h1>Guia Completo de Jardinagem</h1>
          <ul><li>Editora: PENGUIN COMPANHIA</li>
              <li>Número de Páginas: 400</li></ul>
          <p class="preco">R$ 69,69</p>
        </article></body></html>"""
        rel = _verificar([{
            "Título": "Guia Completo de Jardinagem",
            "Editora": "PENGUIN COMPANHIA",
            "Número de Páginas": "400",
            "Preço": "R$ 69,69",
        }], pagina)
        resultado = _campo(rel, 0, "Título")
        self.assertEqual(resultado.veredito, Veredito.SUPORTADA)
        self.assertEqual(rel.registros[0].coesao.campos_fora, [])

    def test_texto_longo_guarda_varias_ocorrencias(self):
        """
        A causa raiz daquele falso positivo: TXT-EXATO guardava só o primeiro
        casamento, deixando a re-ancoragem sem alternativa dentro do item.
        """
        longo = ("Publicado em 1899, Dom Casmurro narra a história de Bentinho, "
                 "que se casa com Capitu e passa a suspeitar de traição")
        pagina = f"""<html><head><meta name="description" content="{longo}"></head>
        <body><article id="p1"><h1>Dom Casmurro</h1>
          <p>{longo}</p>
          <ul><li>Editora: PENGUIN COMPANHIA</li><li>Número de Páginas: 400</li></ul>
        </article></body></html>"""
        rel = _verificar([{
            "Título": "Dom Casmurro", "Descrição": longo,
            "Editora": "PENGUIN COMPANHIA", "Número de Páginas": "400",
        }], pagina)
        descricao = _campo(rel, 0, "Descrição")
        self.assertEqual(descricao.veredito, Veredito.SUPORTADA)
        self.assertGreater(len(descricao.evidencias), 1)
        # a evidência principal deve ser a do corpo do item, não a do <head>
        self.assertIn("article", descricao.evidencia_principal.path)

    def test_modo_texto_nao_reprova_por_localidade(self):
        """Sem árvore, a dispersão é indício fraco demais para reprovar."""
        texto = "Dom Casmurro\nPENGUIN COMPANHIA\n400\nR$ 69,69\nQuincas Borba\n320\nR$ 54,90"
        rel = verificar_dados([self.REGISTRO_MISTURADO], texto, forcar_tipo_fonte="text")
        vereditos = {r.veredito for r in rel.registros[0].resultados}
        self.assertNotIn(Veredito.ATRIBUICAO_INCORRETA, vereditos)


class TestCampoDerivado(unittest.TestCase):
    """O 'Resumo' criado pelo extraction_tool é verificado contra a 'Descrição'."""

    def test_resumo_fiel_a_descricao(self):
        rel = _verificar([{
            "Descrição": "Publicado em 1899, Dom Casmurro narra a história de Bentinho.",
            "Resumo": "Dom Casmurro narra a história de Bentinho.",
        }])
        self.assertEqual(_campo(rel, 0, "Resumo").veredito, Veredito.SUPORTADA)

    def test_resumo_com_entidade_inventada(self):
        rel = _verificar([{
            "Descrição": "Publicado em 1899, Dom Casmurro narra a história de Bentinho.",
            "Resumo": "Dom Casmurro narra a história de Bentinho em Paris.",
        }])
        resultado = _campo(rel, 0, "Resumo")
        self.assertEqual(resultado.veredito, Veredito.NAO_SUPORTADA)
        self.assertEqual(resultado.regra, "DER-CONTEUDO-NOVO")

    def test_resumo_com_numero_inventado(self):
        rel = _verificar([{
            "Descrição": "Publicado em 1899, Dom Casmurro narra a história de Bentinho.",
            "Resumo": "Dom Casmurro, de 1955, narra a história de Bentinho.",
        }])
        self.assertTrue(_campo(rel, 0, "Resumo").alucinacao)

    def test_alucinacao_herdada_da_base(self):
        """Resumo coerente com uma descrição alucinada continua alucinado."""
        rel = _verificar([{
            "Descrição": "Manual técnico de refrigeração industrial com 12 capítulos.",
            "Resumo": "Manual técnico de refrigeração industrial.",
        }])
        resultado = _campo(rel, 0, "Resumo")
        self.assertEqual(resultado.veredito, Veredito.NAO_SUPORTADA)
        self.assertEqual(resultado.regra, "DER-BASE-NAO-ANCORADA")

    def test_limite_de_palavras_do_prompt(self):
        rel = _verificar([{
            "Descrição": "Publicado em 1899, Dom Casmurro narra a história de Bentinho.",
            "Resumo": " ".join(["Bentinho"] * 40),
        }])
        restricao = next(r for r in rel.registros[0].restricoes
                         if r.id == "R-RESUMO-TAMANHO")
        self.assertTrue(restricao.violada)


class TestRestricoes(unittest.TestCase):
    def test_ordem_de_precos(self):
        rel = _verificar([{"Preço Atual": "R$ 69,69", "Preço Antigo": "R$ 54,90"}])
        restricao = next(r for r in rel.registros[0].restricoes if r.id == "R-PRECO-ORDEM")
        self.assertTrue(restricao.violada)

    def test_ordem_de_precos_correta(self):
        rel = _verificar([{"Preço Atual": "R$ 54,90", "Preço Antigo": "R$ 69,69"}])
        restricao = next(r for r in rel.registros[0].restricoes if r.id == "R-PRECO-ORDEM")
        self.assertFalse(restricao.violada)

    def test_registros_duplicados(self):
        registro = {"Título": "Dom Casmurro", "Preço": "R$ 69,69"}
        rel = _verificar([dict(registro), dict(registro)])
        ids = {r.id for r in rel.restricoes_conjunto if r.violada}
        self.assertIn("R-REGISTROS-DUPLICADOS", ids)

    def test_valor_propagado_entre_registros(self):
        rel = _verificar([{"Preço": "R$ 69,69"}] * 3)
        ids = {r.id for r in rel.restricoes_conjunto if r.violada}
        self.assertIn("R-VALOR-CONSTANTE", ids)

    def test_registro_sem_fundamento(self):
        rel = _verificar([{
            "Título": "Livro Inexistente", "Editora": "EDITORA ÁTICA",
            "Preço": "R$ 12,34", "Número de Páginas": "999",
        }])
        ids = {r.id for r in rel.registros[0].restricoes if r.violada}
        self.assertIn("R-REGISTRO-INFUNDADO", ids)


class TestReparo(unittest.TestCase):
    def test_sugestao_vem_da_subarvore_do_registro(self):
        rel = _verificar([{
            "Título": "Dom Casmurro", "Editora": "EDITORA ÁTICA",
            "Número de Páginas": "400", "Preço": "R$ 69,69",
        }])
        sugestoes = rel.registros[0].sugestoes.get("r0:Editora", [])
        self.assertTrue(sugestoes)
        self.assertEqual(sugestoes[0].valor, "PENGUIN COMPANHIA")

    def test_campo_de_outro_item_recebe_o_valor_do_item_correto(self):
        rel = _verificar([{
            "Título": "Quincas Borba",
            "Autor": "ASSIS, MACHADO DE",
            "Editora": "PENGUIN COMPANHIA",       # pertence ao produto 1
            "Número de Páginas": "320",
            "Preço": "R$ 54,90",
        }])
        sugestoes = rel.registros[0].sugestoes.get("r0:Editora", [])
        self.assertTrue(sugestoes)
        self.assertEqual(sugestoes[0].valor, "COMPANHIA DAS LETRAS")

    def test_sem_reparo_quando_desativado(self):
        rel = _verificar([{"Editora": "EDITORA ÁTICA"}], com_reparo=False)
        self.assertEqual(rel.registros[0].sugestoes, {})

    def test_registro_fantasma_nao_recebe_sugestao(self):
        """Preencher um item inexistente com valores de outros seria fabricação."""
        rel = _verificar([{
            "Título": "Livro Inexistente", "Editora": "EDITORA ÁTICA",
            "Preço": "R$ 12,34", "Número de Páginas": "999",
        }])
        self.assertTrue(rel.registros[0].sugestoes)                    # campos listados
        self.assertFalse(any(rel.registros[0].sugestoes.values()))     # sem candidatos

    def test_campo_sem_candidato_vira_indisponivel(self):
        from neurosimbolico import aplicar_reparos
        rel = _verificar([{
            "Título": "Livro Inexistente", "Editora": "EDITORA ÁTICA",
            "Preço": "R$ 12,34", "Número de Páginas": "999",
        }])
        corrigidos = aplicar_reparos([rel.registros[0].registro.dados],
                                     rel.registros[0].sugestoes)
        self.assertEqual(corrigidos[0]["Editora"], "Não disponível")


class TestMetricas(unittest.TestCase):
    def test_abstencao_fora_do_denominador(self):
        rel = _verificar([{"Título": "Dom Casmurro", "Editora": "Não disponível"}])
        self.assertEqual(rel.metricas["afirmacoes_verificaveis"], 1)
        self.assertEqual(rel.metricas["taxa_ancoragem"], 1.0)

    def test_avaliacao_contra_gabarito(self):
        registros = [{"Título": "Dom Casmurro", "Editora": "EDITORA ÁTICA"}]
        gabarito = {"registros": [{"Título": True, "Editora": False}]}
        rel = _verificar(registros, gabarito=gabarito)
        permissivo = rel.avaliacao_gabarito["permissivo"]
        self.assertEqual(permissivo["verdadeiros_positivos"], 1)
        self.assertEqual(permissivo["falsos_positivos"], 0)
        self.assertEqual(permissivo["f1"], 1.0)


class TestExemploCompleto(unittest.TestCase):
    """
    Regressão sobre extração real: página de produto da Livraria Conservadora
    (Memórias Póstumas de Brás Cubas), extraída com gemini-3.6-flash.

    O modelo devolveu 5 registros -- o livro e 4 itens do carrossel de produtos
    relacionados, dos quais só o preço foi capturado. Nenhum valor é alucinado,
    e é a R-COMPLETUDE que sinaliza os registros esvaziados.
    """

    def test_pipeline_na_extracao_real(self):
        rel = verificar(
            EXEMPLOS / "memorias_postumas_data.json",
            EXEMPLOS / "memorias_postumas_text.txt",
        )
        self.assertEqual(rel.metricas["total_registros"], 5)
        self.assertEqual(rel.modo_fonte, "text")
        # nenhum valor inventado: tudo que o modelo afirmou está na página
        self.assertEqual(rel.alucinacoes, [])
        self.assertEqual(rel.metricas["taxa_alucinacao"], 0.0)

    def test_abstencao_nao_infla_a_ancoragem(self):
        rel = verificar(
            EXEMPLOS / "memorias_postumas_data.json",
            EXEMPLOS / "memorias_postumas_text.txt",
        )
        # 30 afirmações, mas só 10 verificáveis: 20 são "Não disponível"
        self.assertEqual(rel.metricas["total_afirmacoes"], 30)
        self.assertEqual(rel.metricas["afirmacoes_verificaveis"], 10)
        self.assertGreater(rel.metricas["taxa_abstencao"], 0.5)

    def test_registros_esvaziados_sao_sinalizados(self):
        rel = verificar(
            EXEMPLOS / "memorias_postumas_data.json",
            EXEMPLOS / "memorias_postumas_text.txt",
        )
        violadas = [r for bloco in rel.registros for r in bloco.restricoes
                    if r.violada and r.id == "R-COMPLETUDE"]
        self.assertEqual(len(violadas), 4)

    def test_resumo_parafraseado_fica_parcial(self):
        """Paráfrase legítima não é alucinação, mas também não é ancoragem."""
        rel = verificar(
            EXEMPLOS / "memorias_postumas_data.json",
            EXEMPLOS / "memorias_postumas_text.txt",
        )
        resumo = next(r for r in rel.registros[4].resultados
                      if r.afirmacao.campo == "Resumo")
        self.assertEqual(resumo.veredito, Veredito.PARCIAL)
        self.assertEqual(resumo.regra, "DER-VINCULO-PARCIAL")

    def test_relatorio_html_e_autocontido(self):
        rel = _verificar([{"Título": "Dom Casmurro"}])
        html = gerar_html(rel)
        self.assertIn("<style>", html)
        self.assertNotIn("http://", html.split("<footer>")[0])
        self.assertIn("Dom Casmurro", html)

    def test_saida_json_serializavel(self):
        rel = _verificar([{"Título": "Dom Casmurro", "Preço": "R$ 69,69"}])
        texto = json.dumps(rel.to_dict(), ensure_ascii=False)
        self.assertIn("SUPORTADA", texto)


class TestConfiguracao(unittest.TestCase):
    def test_limiar_de_resumo_configuravel(self):
        config = Config(resumo_max_palavras=5)
        rel = _verificar([{
            "Descrição": "Publicado em 1899, Dom Casmurro narra a história de Bentinho.",
            "Resumo": "Dom Casmurro narra a história de Bentinho.",
        }], config=config)
        restricao = next(r for r in rel.registros[0].restricoes
                         if r.id == "R-RESUMO-TAMANHO")
        self.assertTrue(restricao.violada)


if __name__ == "__main__":
    unittest.main()
