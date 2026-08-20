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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .afirmacoes import Registro, carregar_registros, decompor
from .config import Config, Veredito
from .dom import SourceIndex, parse_source
from .evidencias import EvidenceBase
from .metricas import agregar, avaliar_contra_gabarito, confiabilidade_registro
from .predicados import ResultadoAfirmacao, verificar_afirmacao
from .reparo import Sugestao, sugerir_correcoes
from .restricoes import (
    Coesao,
    ResultadoRestricao,
    avaliar_conjunto,
    avaliar_registro,
    calcular_coesao,
)

__all__ = ["RelatorioRegistro", "Relatorio", "verificar", "verificar_dados"]

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

    @property
    def nivel(self) -> str:
        if any(r.alucinacao for r in self.resultados):
            return NIVEL_CRITICO
        if any(r.violada and r.severidade == "alta" for r in self.restricoes):
            return NIVEL_CRITICO
        if any(r.veredito == Veredito.PARCIAL for r in self.resultados) or \
           any(r.violada for r in self.restricoes):
            return NIVEL_ATENCAO
        return NIVEL_OK

    def to_dict(self) -> dict:
        return {
            "indice": self.registro.indice,
            "nivel": self.nivel,
            "confiabilidade": self.confiabilidade,
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
        if base is None or not base.alucinacao:
            continue
        resultado.veredito = Veredito.NAO_SUPORTADA
        resultado.regra = "DER-BASE-NAO-ANCORADA"
        resultado.notas.append(
            f"vínculo com '{afirmacao.base_derivacao}' íntegro, porém o próprio "
            f"campo-base não está ancorado na fonte: alucinação herdada")


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
                    origem_fonte: str = "<memória>") -> Relatorio:
    """Executa o pipeline sobre dados já carregados em memória."""
    config = config or Config()
    indice: SourceIndex = parse_source(fonte_bruta, forcar_tipo_fonte)
    base = EvidenceBase(indice)
    registros = decompor(registros_brutos)

    relatorios: List[RelatorioRegistro] = []
    coesoes: List[Coesao] = []
    resultados_por_registro: List[List[ResultadoAfirmacao]] = []

    for registro in registros:
        resultados = [verificar_afirmacao(a, base, config) for a in registro.afirmacoes]
        _propagar_base_derivada(resultados)

        coesao = calcular_coesao(resultados, base, config)
        _aplicar_localidade(resultados, coesao, indice.structural)
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
                    resultado, base, coesao, config)
                sugestoes[resultado.afirmacao.id] = candidatos

        relatorios.append(RelatorioRegistro(
            registro=registro, resultados=resultados, coesao=coesao,
            restricoes=restricoes,
            confiabilidade=confiabilidade_registro(resultados, restricoes),
            sugestoes=sugestoes,
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

    avaliacao = avaliar_contra_gabarito(todas_afirmacoes, gabarito) if gabarito else None

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
    )


def verificar(extracao: str | Path, fonte: str | Path,
              config: Optional[Config] = None,
              gabarito: Any = None,
              com_reparo: bool = True,
              forcar_tipo_fonte: Optional[str] = None) -> Relatorio:
    """
    Verifica um arquivo de extração contra a fonte correspondente.

    `extracao` -- `{task_id}_data.json` ou `.csv` do extraction_tool.
    `fonte`    -- HTML bruto da página ou `{task_id}_text.txt`.
    """
    extracao, fonte = Path(extracao), Path(fonte)
    registros = carregar_registros(extracao)
    bruto = fonte.read_text(encoding="utf-8-sig", errors="replace")
    return verificar_dados(
        registros, bruto, config=config, gabarito=gabarito, com_reparo=com_reparo,
        forcar_tipo_fonte=forcar_tipo_fonte,
        origem_extracao=str(extracao), origem_fonte=str(fonte),
    )
