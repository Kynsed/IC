"""Parâmetros do pipeline de verificação (todos explícitos e auditáveis)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict

__all__ = ["Config", "Veredito", "SEVERIDADE"]


class Veredito:
    """
    Vereditos possíveis para uma afirmação atômica.

    A distinção entre NAO_SUPORTADA e ATRIBUICAO_INCORRETA separa as duas
    famílias de erro descritas na documentação: valores inexistentes na
    página e valores existentes porém associados à posição errada do DOM.
    """
    SUPORTADA = "SUPORTADA"            # ancorada deterministicamente na fonte
    PARCIAL = "PARCIAL"                # suporte incompleto/aproximado
    NAO_SUPORTADA = "NAO_SUPORTADA"    # candidata a alucinação de valor
    ATRIBUICAO_INCORRETA = "ATRIBUICAO_INCORRETA"   # valor de outro item da página
    INVALIDA = "INVALIDA"              # viola restrição de tipo/formato
    ABSTENCAO = "ABSTENCAO"            # modelo declarou ausência do dado
    ERRO_EXTRACAO = "ERRO_EXTRACAO"    # falha da ferramenta, não do conteúdo
    NAO_VERIFICAVEL = "NAO_VERIFICAVEL"

    #: vereditos que contam no denominador das taxas
    CONTABILIZADOS = (SUPORTADA, PARCIAL, NAO_SUPORTADA, ATRIBUICAO_INCORRETA, INVALIDA)
    #: vereditos considerados erro factual
    REPROVADOS = (NAO_SUPORTADA, ATRIBUICAO_INCORRETA, INVALIDA)
    ORDEM = (SUPORTADA, PARCIAL, NAO_SUPORTADA, ATRIBUICAO_INCORRETA, INVALIDA,
             ABSTENCAO, ERRO_EXTRACAO, NAO_VERIFICAVEL)


SEVERIDADE = ("alta", "media", "baixa")


@dataclass
class Config:
    """
    Limiares do verificador.

    Os valores padrão foram escolhidos de forma conservadora: preferem
    classificar como PARCIAL (revisão humana) a declarar SUPORTADA sem
    ancoragem forte.
    """

    # -- cobertura lexical (campos longos) --------------------------------
    cobertura_suporte: float = 0.92
    cobertura_parcial: float = 0.60
    janela_suporte: float = 0.85

    # -- similaridade aproximada ------------------------------------------
    fuzzy_suporte: float = 0.94
    fuzzy_parcial: float = 0.82

    # -- ancoragem numérica ------------------------------------------------
    janela_rotulo: int = 140          # caracteres ao redor do casamento
    score_numero_sem_rotulo: float = 0.60

    # -- campos derivados (Resumo <- Descrição) ---------------------------
    resumo_max_palavras: int = 30     # limite imposto pelo prompt de extração
    resumo_cobertura_minima: float = 0.55

    # -- restrições de domínio ---------------------------------------------
    ano_minimo: int = 1400
    ano_maximo_folga: int = 1          # ano atual + folga

    # -- localidade no DOM --------------------------------------------------
    coesao_minima: float = 0.70
    minimo_campos_coesao: int = 3
    janela_linhas_texto: int = 40      # modo texto: dispersão aceitável

    # -- reparo -------------------------------------------------------------
    sugestoes_por_campo: int = 3

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_file(cls, caminho: str | Path) -> "Config":
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
        conhecidos = {campo for campo in cls().to_dict()}
        return cls(**{k: v for k, v in dados.items() if k in conhecidos})
