"""
Orquestração do pipeline neuro-simbólico de verificação factual.

    saída do LLM (extraction_tool)              fonte (HTML bruto ou texto limpo)
                |                                            |
       decomposição em afirmações                   indexação simbólica
                |                                            |
                +------------------> predicados <------------+
                                         |
                              restrições de registro/conjunto
                                         |
                        veredito + evidência + reparo ancorado

O componente neural (o LLM) não é consultado em nenhuma etapa: a verificação é
integralmente determinística e reprodutível, condição para que os vereditos
sejam auditáveis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import copy
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .afirmacoes import Registro, carregar_registros, decompor
from .config import Config, Veredito
from .contrato import ContractError, canonical_json, schema_sha256, validate_records
from .contexto import verificar_contexto, _identidade
from .proveniencia import carregar_manifesto, sha256
from .dom import SourceIndex, parse_source
from .evidencias import EvidenceBase
from .metricas import agregar, avaliar_contra_gabarito, confiabilidade_registro
from .predicados import ResultadoAfirmacao, verificar_afirmacao
from .reparo import Sugestao, sugerir_correcoes, aplicar_reparos
from .restricoes import (
    Coesao,
    ResultadoRestricao,
    avaliar_conjunto,
    avaliar_registro,
    calcular_coesao,
)

__all__ = ["RelatorioRegistro", "Relatorio", "verificar", "verificar_dados", "reparar_e_reverificar"]

NIVEL_OK, NIVEL_ATENCAO, NIVEL_CRITICO = "ok", "atencao", "critico"


@dataclass
class RelatorioRegistro:
    """Resultado consolidado de um item extraído."""
    registro: Registro
    resultados: List[ResultadoAfirmacao]
    coesao: Coesao
    restricoes: List[ResultadoRestricao]
    confiabilidade: float
    sugestoes: Dict[str, List[Sugestao]] = field(default_factory=dict)
    contextos: dict = field(default_factory=dict)

    @property
    def nivel(self) -> str:
        if any(r.alucinacao or r.veredito == Veredito.ERRO_EXTRACAO for r in self.resultados):
            return NIVEL_CRITICO
        if any(r.violada and r.severidade == "alta" for r in self.restricoes):
            return NIVEL_CRITICO
        if not self.resultados or any(r.veredito in (Veredito.PARCIAL, Veredito.NAO_VERIFICAVEL, Veredito.ABSTENCAO) for r in self.resultados) or \
           any(r.violada for r in self.restricoes):
            return NIVEL_ATENCAO
        return NIVEL_OK

    def to_dict(self) -> dict:
        return {
            "indice": self.registro.indice,
            "nivel": self.nivel,
            "confiabilidade": self.confiabilidade,
            "dados_originais": self.registro.dados,
            "contextos": self.contextos,
            "coesao": {
                "valor": round(self.coesao.valor, 4),
                "aplicavel": self.coesao.aplicavel,
                "ancora": self.coesao.caminho_ancora,
                "campos_fora": self.coesao.campos_fora,
            },
            "afirmacoes": [r.to_dict() for r in self.resultados],
            "restricoes": [r.to_dict() for r in self.restricoes],
            "sugestoes": {k: [s.to_dict() for s in v] for k, v in self.sugestoes.items() if v},
        }


@dataclass
class Relatorio:
    """Relatório completo da verificação."""
    origem_extracao: str
    origem_fonte: str
    modo_fonte: str
    descricao_indice: str
    config: Config
    registros: List[RelatorioRegistro]
    restricoes_conjunto: List[ResultadoRestricao]
    metricas: Dict[str, Any]
    avaliacao_gabarito: Optional[Dict[str, Any]] = None
    gerado_em: str = ""
    schema: Optional[dict] = None
    proveniencia: dict = field(default_factory=dict)

    @property
    def afirmacoes(self) -> List[ResultadoAfirmacao]:
        return [r for reg in self.registros for r in reg.resultados]

    @property
    def alucinacoes(self) -> List[ResultadoAfirmacao]:
        return [r for r in self.afirmacoes if r.alucinacao]

    def to_dict(self) -> dict:
        return {
            "gerado_em": self.gerado_em,
            "origem": {
                "extracao": self.origem_extracao,
                "fonte": self.origem_fonte,
                "modo_fonte": self.modo_fonte,
                "indice": self.descricao_indice,
            },
            "config": self.config.to_dict(),
            "schema": self.schema,
            "proveniencia": self.proveniencia,
            "metricas": self.metricas,
            "avaliacao_gabarito": self.avaliacao_gabarito,
            "restricoes_conjunto": [r.to_dict() for r in self.restricoes_conjunto],
            "registros": [r.to_dict() for r in self.registros],
        }


# ---------------------------------------------------------------------------

def _propagar_base_derivada(resultados: List[ResultadoAfirmacao]) -> None:
    """
    Um campo derivado bem vinculado à sua base continua alucinado se a base
    não estiver ancorada na fonte. A alucinação é herdada, e o relatório
    precisa dizer isso explicitamente.
    """
    por_campo = {r.afirmacao.campo: r for r in resultados}
    for resultado in resultados:
        afirmacao = resultado.afirmacao
        if not afirmacao.derivada or resultado.veredito not in (
                Veredito.SUPORTADA, Veredito.PARCIAL):
            continue
        base = por_campo.get(afirmacao.base_derivacao or "")
        if base is not None and base.veredito == Veredito.SUPORTADA:
            continue
        resultado.veredito = Veredito.NAO_SUPORTADA if base is None or base.alucinacao else Veredito.PARCIAL
        resultado.regra = "DER-BASE-NAO-ANCORADA" if resultado.alucinacao else "DER-BASE-INCONCLUSIVA"
        resultado.notas.append(
            f"vínculo com '{afirmacao.base_derivacao}' íntegro, porém o próprio "
            f"campo-base não tem suporte pleno após a verificação contextual")


def _aplicar_localidade(resultados: List[ResultadoAfirmacao], coesao: Coesao,
                        estrutural: bool) -> None:
    """
    Converte a violação de localidade em veredito da afirmação.

    Um campo cujo valor existe na página, mas não tem nenhuma ocorrência na
    subárvore que ancora o registro, foi colhido de outro item: o valor é real,
    a associação é que é alucinada. Só se aplica no modo estrutural -- no modo
    texto a dispersão de linhas é indício fraco demais para reprovar sozinha.
    """
    if not (estrutural and coesao.aplicavel and coesao.campos_fora):
        return
    fora = set(coesao.campos_fora)
    for resultado in resultados:
        if resultado.afirmacao.campo not in fora:
            continue
        if resultado.veredito not in (Veredito.SUPORTADA, Veredito.PARCIAL):
            continue
        resultado.veredito = Veredito.ATRIBUICAO_INCORRETA
        resultado.regra = "DOM-FORA-DA-ANCORA"
        evidencia = resultado.evidencia_principal
        origem = f" (ancorado em {evidencia.path})" if evidencia else ""
        resultado.notas.append(
            f"o valor existe na página{origem}, mas fora da subárvore do registro "
            f"({coesao.caminho_ancora}): associação campo-item incorreta")


def verificar_dados(registros_brutos: Sequence[Dict[str, Any]], fonte_bruta: str,
                    config: Optional[Config] = None,
                    gabarito: Any = None,
                    com_reparo: bool = True,
                    forcar_tipo_fonte: Optional[str] = None,
                    origem_extracao: str = "<memória>",
                    origem_fonte: str = "<memória>", schema: Optional[dict] = None,
                    proveniencia: Optional[dict] = None) -> Relatorio:
    """Executa o pipeline sobre dados já carregados em memória."""
    config = copy.deepcopy(config) if config is not None else Config()
    config.validate()
    if not isinstance(fonte_bruta, str) or not fonte_bruta.strip():
        raise ValueError("Fonte vazia ou não textual.")
    if forcar_tipo_fonte not in (None, "html", "text"):
        raise ValueError("Tipo de fonte inválido.")
    indice: SourceIndex = parse_source(fonte_bruta, forcar_tipo_fonte)
    base = EvidenceBase(indice)
    registros = decompor(registros_brutos, schema)

    relatorios: List[RelatorioRegistro] = []
    coesoes: List[Coesao] = []
    resultados_por_registro: List[List[ResultadoAfirmacao]] = []

    for registro in registros:
        resultados = [verificar_afirmacao(a, base, config) for a in registro.afirmacoes]
        grupos = defaultdict(list)
        for resultado in resultados:
            grupos[resultado.afirmacao.escopo].append(resultado)
        por_escopo = {}
        for escopo, grupo in grupos.items():
            contexto = list(grupo)
            if not any(_identidade(r) for r in grupo):
                # Objetos que agrupam atributos herdam a entidade mais próxima;
                # não podem buscar atributos livremente em toda a página.
                for tamanho in range(len(escopo) - 1, -1, -1):
                    ancestrais = [r for r in grupos.get(escopo[:tamanho], []) if _identidade(r)]
                    if ancestrais:
                        contexto.extend(copy.deepcopy(ancestrais))
                        break
            por_escopo[escopo] = verificar_contexto(contexto, base, config)
        coesao = next(iter(por_escopo.values())) if len(por_escopo) == 1 else Coesao(0, None, "", [], [], False)
        _propagar_base_derivada(resultados)
        restricoes = avaliar_registro(registro, resultados, base, config, coesao)

        # Um registro sem fundamento na página não tem subárvore de onde extrair
        # correção: qualquer sugestão viria de itens arbitrários e seria, ela
        # própria, fabricação. Nesse caso os campos reprovados são reportados
        # sem candidato -- e `aplicar_reparos` os converte em "Não disponível".
        infundado = any(r.id == "R-REGISTRO-INFUNDADO" and r.violada for r in restricoes)

        sugestoes: Dict[str, List[Sugestao]] = {}
        if com_reparo:
            for resultado in resultados:
                if not resultado.alucinacao:
                    continue
                candidatos = [] if infundado else sugerir_correcoes(
                    resultado, base, por_escopo[resultado.afirmacao.escopo], config)
                sugestoes[resultado.afirmacao.id] = candidatos

        relatorios.append(RelatorioRegistro(
            registro=registro, resultados=resultados, coesao=coesao,
            restricoes=restricoes,
            confiabilidade=confiabilidade_registro(resultados, restricoes),
            sugestoes=sugestoes,
            contextos={"/" + "/".join(map(str, escopo)): {
                "ancora": c.caminho_ancora, "aplicavel": c.aplicavel,
                "valor": c.valor, "campos_fora": c.campos_fora}
                for escopo, c in por_escopo.items()},
        ))
        coesoes.append(coesao)
        resultados_por_registro.append(resultados)

    restricoes_conjunto = avaliar_conjunto(registros, resultados_por_registro,
                                           coesoes, config)

    todas_afirmacoes = [r for lista in resultados_por_registro for r in lista]
    todas_restricoes = [r for rel in relatorios for r in rel.restricoes] + restricoes_conjunto
    metricas = agregar(todas_afirmacoes, todas_restricoes, len(registros))
    metricas["confiabilidade_media"] = (
        round(sum(r.confiabilidade for r in relatorios) / len(relatorios), 4)
        if relatorios else 0.0
    )
    metricas["registros_por_nivel"] = {
        nivel: sum(1 for r in relatorios if r.nivel == nivel)
        for nivel in (NIVEL_OK, NIVEL_ATENCAO, NIVEL_CRITICO)
    }

    avaliacao = avaliar_contra_gabarito(todas_afirmacoes, gabarito) if gabarito is not None else None
    proveniencia = copy.deepcopy(proveniencia) if proveniencia else {
        "estado": "dados_em_memoria", "execucao_id": None}
    proveniencia.update({
        "fonte_texto_sha256": sha256(fonte_bruta.encode("utf-8")),
        "registros_canonicos_sha256": sha256(canonical_json(registros_brutos).encode("utf-8")),
        "schema_sha256": schema_sha256(schema) if schema else None})

    return Relatorio(
        origem_extracao=origem_extracao,
        origem_fonte=origem_fonte,
        modo_fonte=indice.kind,
        descricao_indice=indice.describe(),
        config=config,
        registros=relatorios,
        restricoes_conjunto=restricoes_conjunto,
        metricas=metricas,
        avaliacao_gabarito=avaliacao,
        gerado_em=datetime.now().isoformat(timespec="seconds"),
        schema=copy.deepcopy(schema),
        proveniencia=proveniencia,
    )


def verificar(extracao: str | Path, fonte: str | Path,
              config: Optional[Config] = None,
              gabarito: Any = None,
              com_reparo: bool = True,
              forcar_tipo_fonte: Optional[str] = None, schema: Optional[dict] = None) -> Relatorio:
    """
    Verifica um arquivo de extração contra a fonte correspondente.

    `extracao` -- `{task_id}_data.json` ou `.csv` do extraction_tool.
    `fonte`    -- HTML bruto da página ou `{task_id}_text.txt`.
    """
    extracao, fonte = Path(extracao), Path(fonte)
    schema, proveniencia = carregar_manifesto(extracao, fonte, schema)
    registros = carregar_registros(extracao, schema)
    if extracao.suffix.lower() == ".csv":
        proveniencia["transformacoes"] = ["CSV decodificado conforme tipos explícitos do schema" if schema else "CSV mantido como strings; tipos originais não recuperáveis"]
    bruto = fonte.read_text(encoding="utf-8-sig")
    return verificar_dados(
        registros, bruto, config=config, gabarito=gabarito, com_reparo=com_reparo,
        forcar_tipo_fonte=forcar_tipo_fonte,
        origem_extracao=str(extracao), origem_fonte=str(fonte),
        schema=schema, proveniencia=proveniencia,
    )


def reparar_e_reverificar(relatorio: Relatorio, fonte_bruta: str):
    """Aplica candidatos tipados individualmente e só aceita suporte contextual final.

    A ausência de candidato pode virar abstenção se o contrato permitir; isso
    é remoção de erro, não recuperação de fato. Toda tentativa é auditada.
    """
    dados = copy.deepcopy([r.registro.dados for r in relatorio.registros])
    if sha256(fonte_bruta.encode("utf-8")) != relatorio.proveniencia.get("fonte_texto_sha256"):
        raise ContractError("Reparo exige o mesmo snapshot textual da verificação original.")
    mudancas = []
    def reverificar(candidatos):
        return verificar_dados(candidatos, fonte_bruta, config=copy.deepcopy(relatorio.config),
            com_reparo=False, forcar_tipo_fonte=relatorio.modo_fonte,
            origem_extracao=relatorio.origem_extracao, origem_fonte=relatorio.origem_fonte,
            schema=relatorio.schema, proveniencia={**relatorio.proveniencia, "etapa": "pos_reparo"})
    atual = reverificar(dados)
    for bloco in relatorio.registros:
        for chave, sugestoes in bloco.sugestoes.items():
            antes = next(r for r in atual.afirmacoes if r.afirmacao.id == chave)
            if not antes.alucinacao:
                continue
            # Um reparo não pode trocar a entidade consultada por outra da página.
            identidade = antes.afirmacao.identidade or antes.afirmacao.campo_original.casefold() in {
                "nome", "name", "nome completo", "full name", "título", "titulo", "title",
                "produto", "product", "id", "identificador", "identifier"}
            if identidade:
                sugestoes = []
            tentativas = [[s] for s in sugestoes] + [[]]
            for proposta in tentativas:
                log = {"afirmacao": chave, "antes": antes.afirmacao.valor_bruto,
                       "candidato": proposta[0].valor if proposta else None,
                       "evidencia": proposta[0].to_dict() if proposta else None}
                try:
                    candidatos = aplicar_reparos(dados, {chave: proposta}, schema=relatorio.schema)
                    pos = reverificar(candidatos)
                    depois = next(r for r in pos.afirmacoes if r.afirmacao.id == chave)
                    antigos = {r.afirmacao.id: r for r in atual.afirmacoes}
                    regressao = any(antigos[r.afirmacao.id].veredito == Veredito.SUPORTADA
                                     and r.veredito != Veredito.SUPORTADA for r in pos.afirmacoes)
                    aceito = (depois.veredito == (Veredito.SUPORTADA if proposta else Veredito.ABSTENCAO)
                              and not regressao)
                    log.update(depois=depois.afirmacao.valor_bruto, veredito_pos=depois.veredito,
                               aceito=aceito, motivo="suporte confirmado" if aceito and proposta else
                               "abstenção permitida" if aceito else "sem suporte pleno ou regressão")
                    if aceito:
                        dados, atual = candidatos, pos
                except (ValueError, TypeError) as exc:
                    aceito = False
                    log.update(aceito=False, motivo=str(exc))
                mudancas.append(log)
                if aceito:
                    break
    return dados, atual, mudancas
