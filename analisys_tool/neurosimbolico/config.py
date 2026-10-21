"""Parâmetros do pipeline de verificação (todos explícitos e auditáveis)."""

from __future__ import annotations

import json
import math
from datetime import date
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
    data_referencia: str = field(default_factory=lambda: date.today().isoformat())

    def validate(self) -> None:
        date.fromisoformat(self.data_referencia)
        for nome in ("cobertura_suporte", "cobertura_parcial", "janela_suporte",
                     "fuzzy_suporte", "fuzzy_parcial", "score_numero_sem_rotulo",
                     "resumo_cobertura_minima", "coesao_minima"):
            valor = getattr(self, nome)
            if type(valor) not in (int, float) or not math.isfinite(valor) or not 0 <= valor <= 1:
                raise ValueError(f"{nome} deve estar entre 0 e 1.")
        for nome in ("janela_rotulo", "resumo_max_palavras", "ano_minimo", "ano_maximo_folga",
                     "minimo_campos_coesao", "janela_linhas_texto", "sugestoes_por_campo"):
            if type(getattr(self, nome)) is not int or getattr(self, nome) < 0:
                raise ValueError(f"{nome} deve ser inteiro não negativo.")
        if self.cobertura_parcial > self.cobertura_suporte or self.fuzzy_parcial > self.fuzzy_suporte:
            raise ValueError("Limiar parcial não pode superar o de suporte.")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_file(cls, caminho: str | Path) -> "Config":
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
        conhecidos = {campo for campo in cls().to_dict()}
        if not isinstance(dados, dict) or set(dados) - conhecidos:
            raise ValueError("Configuração contém campos desconhecidos ou formato inválido.")
        config = cls(**dados)
        config.validate()
        return config
