"""
Métricas de factualidade e avaliação do próprio verificador.

Duas camadas distintas:

1. `agregar()`  -- mede a saída do LLM: taxa de ancoragem, taxa de alucinação,
   abstenção, violações de restrição, por campo e por tipo semântico.
2. `avaliar_contra_gabarito()` -- mede o **verificador**: dado um gabarito
   anotado manualmente, calcula precisão/revocação/F1 da detecção de
   alucinações. É essa a métrica reportável na seção de Resultados.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .config import Veredito
from .predicados import ResultadoAfirmacao
from .restricoes import ResultadoRestricao

__all__ = ["agregar", "confiabilidade_registro", "avaliar_contra_gabarito"]

_PESOS = {
    Veredito.SUPORTADA: 1.0,
    Veredito.PARCIAL: 0.5,
    Veredito.NAO_SUPORTADA: 0.0,
    Veredito.ATRIBUICAO_INCORRETA: 0.0,
    Veredito.INVALIDA: 0.0,
}
_PENALIDADE_SEVERIDADE = {"alta": 0.20, "media": 0.10, "baixa": 0.03}


def _taxa(numerador: int, denominador: int) -> float:
    return round(numerador / denominador, 4) if denominador else 0.0


def confiabilidade_registro(resultados: Sequence[ResultadoAfirmacao],
                            restricoes: Sequence[ResultadoRestricao]) -> float:
    """
    Índice de confiabilidade de um registro em [0, 1].

    Média dos pesos dos vereditos verificáveis, penalizada pelas restrições
    violadas (uma violação de coesão no DOM compromete o registro inteiro,
    ainda que cada valor isolado exista na página).
    """
    pesos = [_PESOS[r.veredito] for r in resultados if r.veredito in _PESOS]
    base = sum(pesos) / len(pesos) if pesos else 0.0
    penalidade = sum(_PENALIDADE_SEVERIDADE.get(r.severidade, 0.05)
                     for r in restricoes if r.violada)
    return round(max(0.0, base - penalidade), 4)


def agregar(resultados: Sequence[ResultadoAfirmacao],
            restricoes: Sequence[ResultadoRestricao],
            total_registros: int) -> Dict[str, Any]:
    """Consolida as métricas de factualidade da extração."""
    por_veredito = Counter(r.veredito for r in resultados)
    verificaveis = sum(por_veredito[v] for v in Veredito.CONTABILIZADOS)
    alucinacoes = sum(por_veredito[v] for v in Veredito.REPROVADOS)

    por_campo: Dict[str, Counter] = defaultdict(Counter)
    por_tipo: Dict[str, Counter] = defaultdict(Counter)
    por_regra: Counter = Counter()
    for resultado in resultados:
        por_campo[resultado.afirmacao.campo][resultado.veredito] += 1
        por_tipo[resultado.afirmacao.tipo][resultado.veredito] += 1
        por_regra[resultado.regra] += 1

    def _resumo(contador: Counter) -> Dict[str, Any]:
        local_verificaveis = sum(contador[v] for v in Veredito.CONTABILIZADOS)
        local_alucinacoes = sum(contador[v] for v in Veredito.REPROVADOS)
        return {
            "total": sum(contador.values()),
            "vereditos": {v: contador[v] for v in Veredito.ORDEM if contador[v]},
            "taxa_ancoragem": _taxa(contador[Veredito.SUPORTADA], local_verificaveis),
            "taxa_alucinacao": _taxa(local_alucinacoes, local_verificaveis),
        }

    violadas = [r for r in restricoes if r.violada]
    return {
        "total_registros": total_registros,
        "total_afirmacoes": len(resultados),
        "afirmacoes_verificaveis": verificaveis,
        "vereditos": {v: por_veredito[v] for v in Veredito.ORDEM},
        "taxa_ancoragem": _taxa(por_veredito[Veredito.SUPORTADA], verificaveis),
        "taxa_suporte_parcial": _taxa(por_veredito[Veredito.PARCIAL], verificaveis),
        "taxa_alucinacao": _taxa(alucinacoes, verificaveis),
        "taxa_abstencao": _taxa(por_veredito[Veredito.ABSTENCAO], len(resultados)),
        "restricoes_violadas": dict(Counter(r.id for r in violadas)),
        "restricoes_violadas_total": len(violadas),
        "por_campo": {campo: _resumo(c) for campo, c in sorted(por_campo.items())},
        "por_tipo": {tipo: _resumo(c) for tipo, c in sorted(por_tipo.items())},
        "regras_acionadas": dict(por_regra.most_common()),
    }


# ---------------------------------------------------------------------------
# Avaliação do verificador contra gabarito anotado
# ---------------------------------------------------------------------------

def _gabarito_por_chave(gabarito: Any) -> Dict[str, bool]:
    """
    Aceita:
      [{"Título": true, "Preço": false}, ...]        (alinhado por índice)
      {"registros": [ ... ]}
      {"r0:Preço": false, ...}                        (chaves diretas)

    Valor `true` = o dado extraído está correto; `false` = incorreto.
    """
    if isinstance(gabarito, dict) and "registros" in gabarito:
        gabarito = gabarito["registros"]

    saida: Dict[str, bool] = {}
    if isinstance(gabarito, dict):
        for chave, valor in gabarito.items():
            saida[chave] = _para_bool(valor)
        return saida
    for indice, registro in enumerate(gabarito or []):
        if not isinstance(registro, dict):
            continue
        for campo, valor in registro.items():
            saida[f"r{indice}:{campo}"] = _para_bool(valor)
    return saida


def _para_bool(valor: Any) -> bool:
    if isinstance(valor, bool):
        return valor
    texto = str(valor).strip().lower()
    return texto in ("true", "1", "sim", "correto", "ok", "certo", "y", "yes")


def avaliar_contra_gabarito(resultados: Sequence[ResultadoAfirmacao],
                            gabarito: Any) -> Dict[str, Any]:
    """
    Precisão/revocação/F1 da detecção de alucinações.

    Classe positiva = "afirmação incorreta". Reporta dois regimes de decisão:
    `estrito` conta PARCIAL como detecção; `permissivo` só conta
    NAO_SUPORTADA e INVALIDA.
    """
    referencia = _gabarito_por_chave(gabarito)
    if not referencia:
        return {"erro": "gabarito vazio ou em formato não reconhecido"}

    regimes = {
        "permissivo": Veredito.REPROVADOS,
        "estrito": Veredito.REPROVADOS + (Veredito.PARCIAL,),
    }
    saida: Dict[str, Any] = {"afirmacoes_anotadas": 0}
    detalhes: List[Dict[str, Any]] = []

    for nome, positivos in regimes.items():
        vp = fp = vn = fn = 0
        for resultado in resultados:
            chave = resultado.afirmacao.id
            if chave not in referencia:
                continue
            correto = referencia[chave]
            detectou = resultado.veredito in positivos
            if not correto and detectou:
                vp += 1
            elif correto and detectou:
                fp += 1
            elif correto and not detectou:
                vn += 1
            else:
                fn += 1
                if nome == "permissivo":
                    detalhes.append({
                        "afirmacao": chave, "valor": resultado.afirmacao.valor,
                        "veredito": resultado.veredito, "regra": resultado.regra,
                    })
        precisao = _taxa(vp, vp + fp)
        revocacao = _taxa(vp, vp + fn)
        f1 = round(2 * precisao * revocacao / (precisao + revocacao), 4) if (precisao + revocacao) else 0.0
        saida[nome] = {
            "verdadeiros_positivos": vp, "falsos_positivos": fp,
            "verdadeiros_negativos": vn, "falsos_negativos": fn,
            "precisao": precisao, "revocacao": revocacao, "f1": f1,
            "acuracia": _taxa(vp + vn, vp + fp + vn + fn),
        }
        saida["afirmacoes_anotadas"] = vp + fp + vn + fn

    saida["alucinacoes_nao_detectadas"] = detalhes[:50]
    return saida
