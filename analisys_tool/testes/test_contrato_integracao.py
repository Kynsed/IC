"""Contrato, proveniência e reparo: regressões independentes de APIs externas."""
import copy
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neurosimbolico.afirmacoes import decompor, ler_registros
from neurosimbolico.config import Config, Veredito
from neurosimbolico.contrato import (ContractError, build_schema, canonical_json,
                                   parse_response, schema_sha256, validate_records, validate_schema)
from neurosimbolico.metricas import avaliar_contra_gabarito
from neurosimbolico.proveniencia import sha256
from neurosimbolico.reparo import Sugestao, aplicar_reparos
from neurosimbolico.verificador import verificar, verificar_dados, reparar_e_reverificar


def contrato_pessoa():
    return {"type": "array", "items": {"type": "object", "properties": {
        "nome": {"type": "string", "x-entity-key": True},
        "idade": {"type": ["integer", "null"]}},
        "required": ["nome", "idade"], "additionalProperties": False}}


class TestContrato(unittest.TestCase):
    def test_parse_completo_nested_sem_regex_interna(self):
        schema = {"type": "array", "items": {"type": "object", "properties": {
            "pessoas": contrato_pessoa()}, "required": ["pessoas"], "additionalProperties": False}}
        dados = [{"pessoas": [{"nome": "Ana", "idade": 0}]}]
        self.assertEqual(parse_response("```json\n" + json.dumps(dados) + "\n```", schema), dados)
        a = decompor(dados, schema)[0].afirmacoes
        self.assertEqual(a[1].campo, "/pessoas/0/idade")
        self.assertEqual(a[1].valor_bruto, 0)
        self.assertEqual(a[1].escopo, ("pessoas", 0))
        self.assertTrue(a[0].identidade)

    def test_rejeita_tipos_faltantes_extras_e_primitivos(self):
        schema = contrato_pessoa()
        for dados in ([{"nome": "Ana"}], [{"nome": "Ana", "idade": "30"}],
                      [{"nome": "Ana", "idade": False}], [{"nome": "Ana", "idade": 30, "x": 1}],
                      None, "string", [1]):
            with self.subTest(dados=dados), self.assertRaises(ContractError):
                validate_records(dados, schema)

    def test_json_duplicado_nan_lixo_rejeitados(self):
        schema = build_schema(["nome"], False)
        for texto in ('[{"nome":"Ana","nome":"Maria"}]', '[{"nome":NaN}]',
                      'texto [{"nome":"Ana"}]', '[{"nome":"Ana"}] resto'):
            with self.subTest(texto=texto), self.assertRaises(ContractError):
                parse_response(texto, schema)

    def test_keyword_nao_suportada_rejeitada(self):
        schema = contrato_pessoa()
        schema["uniqueItems"] = True
        with self.assertRaises(ContractError):
            validate_schema(schema)

    def test_schema_nao_aceita_wrapper_ou_objeto_unico(self):
        for dados in ({"nome": "Ana", "idade": 30}, {"data": [{"nome": "Ana", "idade": 30}]}):
            with self.subTest(dados=dados), self.assertRaises(ContractError):
                ler_registros(json.dumps(dados), schema=contrato_pessoa())

    def test_enum_numerico_schema_sem_confundir_bool(self):
        schema = build_schema(["n"], False)
        schema["items"]["properties"]["n"] = {"type": ["number", "boolean"], "enum": [1]}
        validate_records([{"n": 1.0}], schema)
        with self.assertRaises(ContractError):
            validate_records([{"n": True}], schema)
        schema["items"]["properties"]["n"] = {"type": "number"}
        validate_records([{"n": 10 ** 400}], schema)

    def test_csv_preserva_quebra_interna(self):
        self.assertEqual(ler_registros('nome,descricao\r\nAna,"linha1\r\nlinha2"\r\n', "csv"),
                         [{"nome": "Ana", "descricao": "linha1\r\nlinha2"}])

    def test_csv_contrato_converte_so_tipos_declarados(self):
        self.assertEqual(ler_registros("nome,idade\nAna,0\n", "csv", contrato_pessoa()), [{"nome": "Ana", "idade": 0}])
        with self.assertRaises(ContractError):
            ler_registros("nome\n0\n", "csv", build_schema(["nome"], False))
        with self.assertRaises(ContractError):
            ler_registros("nome,nome\nAna,Maria\n", "csv")

    def test_config_rejeita_nan_e_desconhecidos(self):
        with self.assertRaises(ValueError):
            Config(coesao_minima=float("nan")).validate()

    def test_gabarito_rejeita_rotulo_desconhecido_e_conta_cobertura(self):
        r = verificar_dados([{"nome": "Ana", "idade": 30}], "Nome: Ana; Idade: 30")
        with self.assertRaises(ValueError):
            avaliar_contra_gabarito(r.afirmacoes, [{"nome": "talvez"}])
        m = avaliar_contra_gabarito(r.afirmacoes, {"r0:nome": True, "r1:nome": False})
        self.assertEqual(m["afirmacoes_sem_rotulo"], ["r0:idade"])
        self.assertEqual(m["rotulos_sem_afirmacao"], ["r1:nome"])

    def test_falha_operacional_nao_e_nivel_ok(self):
        r = verificar_dados([{"nome": "Erro na extração"}], "qualquer fonte")
        self.assertEqual(r.registros[0].resultados[0].veredito, Veredito.ERRO_EXTRACAO)
        self.assertEqual(r.registros[0].nivel, "critico")


class TestReparo(unittest.TestCase):
    fonte = "<article><h2>Maria</h2><p>Idade: 30</p><p>Casa: 45</p></article><article><h2>João</h2><p>Idade: 45</p></article>"

    def test_reparo_tipado_nested_sem_mutacao(self):
        dados = [{"pessoas": [{"nome": "Maria", "idade": 45}]}]
        schema = {"type": "array", "items": {"type": "object", "properties": {"pessoas": contrato_pessoa()}, "additionalProperties": False}}
        sugestao = Sugestao("30", 1, "/article/p", "idade explícita")
        corrigido = aplicar_reparos(dados, {"r0:/pessoas/0/idade": [sugestao]}, schema)
        self.assertEqual(corrigido[0]["pessoas"][0]["idade"], 30)
        self.assertEqual(dados[0]["pessoas"][0]["idade"], 45)

    def test_reverificacao_recusa_sugestao_de_outro_atributo(self):
        r = verificar_dados([{"nome": "Maria", "idade": 99}], self.fonte, schema=contrato_pessoa())
        r.registros[0].sugestoes["r0:idade"] = [Sugestao("45", 1, "falso", "candidato adversarial")]
        dados, pos, log = reparar_e_reverificar(r, self.fonte)
        self.assertFalse(log[0]["aceito"])
        self.assertIsNone(dados[0]["idade"])
        self.assertEqual(pos.registros[0].resultados[1].veredito, Veredito.ABSTENCAO)

    def test_reparo_nao_muda_identidade(self):
        r = verificar_dados([{"nome": "Pedro", "idade": 99}], self.fonte, schema=contrato_pessoa())
        r.registros[0].sugestoes["r0:nome"] = [Sugestao("João", 1, "falso", "troca de entidade")]
        dados, _, log = reparar_e_reverificar(r, self.fonte)
        self.assertEqual(dados[0]["nome"], "Pedro")
        self.assertTrue(any(not x["aceito"] for x in log))

    def test_reparo_exige_mesma_fonte(self):
        r = verificar_dados([{"nome": "Maria", "idade": 99}], self.fonte)
        with self.assertRaises(ContractError):
            reparar_e_reverificar(r, self.fonte + "alterada")

    def test_atributo_aninhado_herda_identidade_do_pai(self):
        r = verificar_dados([{"nome": "Maria", "perfil": {"idade": 45}}], self.fonte)
        idade = next(x for x in r.afirmacoes if x.afirmacao.campo == "/perfil/idade")
        self.assertEqual(idade.veredito, Veredito.ATRIBUICAO_INCORRETA)

    def test_config_original_nao_altera_relatorio(self):
        config = Config(coesao_minima=0.7)
        r = verificar_dados([{"nome": "Maria"}], self.fonte, config=config)
        config.coesao_minima = 0
        self.assertEqual(r.config.coesao_minima, 0.7)

    def test_derivado_herda_contexto_final_da_base(self):
        descricao = "Um livro sobre pessoas e viagens pelas terras de Portugal."
        fonte = f"<article><h2>Maria</h2><p>Descrição: Outra descrição.</p></article><article><h2>João</h2><p>Descrição: {descricao}</p></article>"
        r = verificar_dados([{"nome": "Maria", "Descrição": descricao, "Resumo": descricao}], fonte)
        por_campo = {x.afirmacao.campo: x for x in r.afirmacoes}
        self.assertEqual(por_campo["Descrição"].veredito, Veredito.ATRIBUICAO_INCORRETA)
        self.assertEqual(por_campo["Resumo"].veredito, Veredito.NAO_SUPORTADA)
        self.assertEqual(por_campo["Resumo"].regra, "DER-BASE-NAO-ANCORADA")

    def test_derivado_sem_base_nao_escapa_para_matching_direto(self):
        for base in (None, "", "Não disponível"):
            r = verificar_dados([{"nome": "Maria", "Descricao": base, "Resumo": "Maria nasceu em Lisboa"}],
                "<article><h2>Maria</h2><p>Resumo: Maria nasceu em Lisboa</p></article>")
            resumo = next(x for x in r.afirmacoes if x.afirmacao.campo == "Resumo")
            self.assertTrue(resumo.afirmacao.derivada)
            self.assertEqual(resumo.veredito, Veredito.NAO_VERIFICAVEL)


class TestManifesto(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.raiz = Path(self.temp.name)
        self.extracao = self.raiz / "abc_data.json"
        self.fonte = self.raiz / "abc.html"
        schema = contrato_pessoa()
        artefatos = {"source": (self.fonte, '<article><h2>Maria</h2><p>Idade: 30</p></article>'),
            "extraction": (self.extracao, '[{"nome":"Maria","idade":30}]'),
            "processed_input": (self.raiz / "abc_text.txt", "Maria Idade: 30"),
            "prompt": (self.raiz / "abc_prompt.txt", "extrair"),
            "raw_response": (self.raiz / "abc_raw.txt", '[{"nome":"Maria","idade":30}]')}
        self.manifesto = {"manifest_version": 1, "task_id": "abc", "status": "completed",
                          "schema": schema, "schema_sha256": schema_sha256(schema), "provider": {"name": "stub"}}
        for nome, (path, texto) in artefatos.items():
            path.write_bytes(texto.encode("utf-8"))
            self.manifesto[nome] = {"path": path.name, "sha256": sha256(path.read_bytes())}
        self.manifesto["source"]["kind"] = "html"
        self.salvar()

    def salvar(self):
        (self.raiz / "abc_manifest.json").write_text(json.dumps(self.manifesto), encoding="utf-8")

    def test_vincula_schema_e_snapshot(self):
        r = verificar(self.extracao, self.fonte)
        self.assertEqual(r.proveniencia["execucao_id"], "abc")
        self.assertEqual(r.proveniencia["estado"], "manifesto_validado")
        self.assertEqual(r.schema, contrato_pessoa())

    def test_tamper_raw_rejeitado(self):
        (self.raiz / "abc_raw.txt").write_text("alterada", encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "hash divergente"):
            verificar(self.extracao, self.fonte)

    def test_fonte_trocada_e_imagem_rejeitadas(self):
        outra = self.raiz / "outra.html"
        outra.write_bytes(self.fonte.read_bytes())
        with self.assertRaises(ContractError):
            verificar(self.extracao, outra)
        self.manifesto["source"]["kind"] = "image"
        self.salvar()
        with self.assertRaisesRegex(ContractError, "OCR"):
            verificar(self.extracao, self.fonte)

    def test_escapada_de_diretorio_rejeitada(self):
        self.manifesto["raw_response"]["path"] = "../externo.txt"
        self.salvar()
        with self.assertRaisesRegex(ContractError, "Caminho inválido"):
            verificar(self.extracao, self.fonte)


class TestWeb(unittest.TestCase):
    def setUp(self):
        try:
            from neurosimbolico import servidor
        except ImportError:
            self.skipTest("Flask não instalado neste runtime")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.patch = patch.object(servidor, "PASTA_SAIDA", Path(temp.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        app = servidor.criar_app()
        app.testing = True
        self.client = app.test_client()

    def test_json_invalido_nao_vira_csv(self):
        for texto in ('[', 'null', '"texto"', '[1]'):
            with self.subTest(texto=texto):
                resposta = self.client.post("/verificar", data={"extracao_texto": texto, "fonte_texto": "Nome: Ana"})
                self.assertEqual(resposta.status_code, 400)

    def test_limite_invalido_rejeitado(self):
        resposta = self.client.post("/verificar", data={"extracao_texto": '[{"nome":"Ana"}]', "fonte_texto": "Nome: Ana", "coesao_minima": "nan"})
        self.assertEqual(resposta.status_code, 400)

    def test_upload_csv_explicito(self):
        resposta = self.client.post("/verificar", data={"extracao": (io.BytesIO(b"nome\nAna\n"), "dados.csv"), "fonte_texto": "Nome: Ana"})
        self.assertEqual(resposta.status_code, 200)


class TestCLI(unittest.TestCase):
    def test_gera_copia_tipado_auditoria_e_relatorio_pos(self):
        from neurosimbolico.cli import main
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            fonte = raiz / "fonte.html"
            fonte.write_text(TestReparo.fonte, encoding="utf-8")
            dados = raiz / "dados.json"
            dados.write_text('[{"nome":"Maria","idade":99}]', encoding="utf-8")
            schema = raiz / "schema.json"
            schema.write_text(json.dumps(contrato_pessoa()), encoding="utf-8")
            saida = raiz / "saida"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                codigo = main(["verificar", "--extracao", str(dados), "--fonte", str(fonte),
                    "--schema", str(schema), "--saida", str(saida), "--aplicar-reparos"])
            self.assertEqual(codigo, 0)
            self.assertEqual(json.loads(dados.read_text())[0]["idade"], 99)
            corrigidos = json.loads((saida / "dados_corrigido.json").read_text(encoding="utf-8"))
            self.assertEqual(corrigidos[0]["idade"], 30)
            posterior = json.loads((saida / "dados_pos_reparo.json").read_text(encoding="utf-8"))
            self.assertEqual(posterior["metricas"]["vereditos"]["SUPORTADA"], 2)
            auditoria = json.loads((saida / "dados_reparos.json").read_text(encoding="utf-8"))
            self.assertTrue(auditoria["tentativas"][0]["aceito"])
            self.assertTrue((saida / "dados_relatorio.html").is_file())

    def test_opcoes_de_reparo_incompativeis(self):
        from neurosimbolico.cli import main
        with redirect_stderr(io.StringIO()):
            codigo = main(["verificar", "--extracao", "nao_ler.json", "--fonte", "nao_ler.html",
                           "--sem-reparo", "--aplicar-reparos"])
        self.assertEqual(codigo, 2)


if __name__ == "__main__":
    unittest.main()
