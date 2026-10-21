"""
Restrições simbólicas de nível de registro e de conjunto.

Enquanto os predicados de `predicados.py` verificam cada afirmação isoladamente
contra a fonte, este módulo verifica a *coerência* entre afirmações. É aqui que
se detecta a segunda família de erros descrita na documentação: associações de
informação em posições incorretas do DOM -- valores que existem na página, mas
pertencem a outro item.

A regra R-COESAO-DOM formaliza essa noção: os campos de um mesmo registro devem
estar ancorados em uma mesma subárvore do documento.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from math import ceil
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .afirmacoes import Registro
from .config import Config, Veredito
from .evidencias import EvidenceBase
from .normalizacao import decimal_variants, normalize, parse_date, word_count
from .predicados import ResultadoAfirmacao

__all__ = ["ResultadoRestricao", "Coesao", "avaliar_registro",
           "avaliar_conjunto", "calcular_coesao"]

OK, VIOLADA, NAO_APLICAVEL = "OK", "VIOLADA", "NAO_APLICAVEL"

_TERMOS_PRECO_ATUAL = ("atual", "current", "promocional", "por", "venda", "oferta", "final")
_TERMOS_PRECO_ANTIGO = ("antigo", "old", "original", "cheio", "lista", "de", "anterior", "sem desconto")


@dataclass
class ResultadoRestricao:
    """Resultado da avaliação de uma restrição."""
    id: str
    escopo: str                      # 'registro' | 'conjunto'
    status: str
    severidade: str
    mensagem: str
    registro: Optional[int] = None
    campos: List[str] = field(default_factory=list)

    @property
    def violada(self) -> bool:
        return self.status == VIOLADA

    def to_dict(self) -> dict:
        return {
            "id": self.id, "escopo": self.escopo, "status": self.status,
            "severidade": self.severidade, "mensagem": self.mensagem,
            "registro": self.registro, "campos": self.campos,
        }


@dataclass
class Coesao:
    """Medida de localidade das evidências de um registro."""
    valor: float
    ancora: Optional[int]            # nó do DOM que ancora o registro
    caminho_ancora: str
    campos_ancorados: List[str]
    campos_fora: List[str]
    aplicavel: bool
    chunks_ancora: List[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Localidade no DOM
# ---------------------------------------------------------------------------

def calcular_coesao(resultados: Sequence[ResultadoAfirmacao],
                    base: EvidenceBase, config: Config) -> Coesao:
    """
    Localiza a subárvore que ancora o registro e identifica os campos fora dela.

    A **âncora** é definida como a subárvore *mais específica* (mais profunda)
    que concentra ao menos `coesao_minima` dos campos ancorados do registro.
    Tomar simplesmente o ancestral comum de todos os campos não funcionaria:
    ele sobe até o contêiner que engloba a página inteira, e nenhum campo
    deslocado jamais ficaria de fora.

    Como um mesmo valor pode ocorrer em vários pontos da página (o autor
    aparece em todos os livros do catálogo), cada campo é **re-ancorado**: se
    alguma de suas evidências estiver dentro da âncora, é ela que passa a ser a
    evidência principal. Só é reportado como fora quem não tem *nenhuma*
    ocorrência na subárvore do registro -- esse é o valor colhido de outro item.

    Efeito colateral intencional: reordena `resultado.evidencias`.
    """
    indice_fonte = base.index

    def _em_metadados(no: Optional[int]) -> bool:
        """
        Evidência dentro de <head> (meta, title) é metadado da página inteira,
        não conteúdo de um item. Nunca caracteriza 'valor de outro item', então
        é ignorada aqui -- do contrário, um título que casa primeiro com
        <meta name="citation_title"> seria acusado de atribuição incorreta.
        """
        if no is None or not indice_fonte.structural:
            return False
        return any(indice_fonte.nodes[a].tag == "head"
                   for a in (no, *indice_fonte.ancestors(no)))

    candidatos: List[Tuple[ResultadoAfirmacao, Dict[int, List]]] = []
    for resultado in resultados:
        if resultado.veredito not in (Veredito.SUPORTADA, Veredito.PARCIAL):
            continue
        por_no: Dict[int, List] = {}
        for evidencia in resultado.evidencias:
            no = base.node_of_evidence(evidencia)
            if no is not None and not _em_metadados(no):
                por_no.setdefault(no, []).append(evidencia)
        if por_no:
            candidatos.append((resultado, por_no))

    campos = [r.afirmacao.campo for r, _ in candidatos]
    if len(candidatos) < config.minimo_campos_coesao:
        return Coesao(1.0, None, "", campos, [], False)

    indice = base.index

    if indice.structural:
        # cobertura[no] = campos com ao menos uma evidência na subárvore de `no`
        cobertura: Dict[int, Set[str]] = {}
        for resultado, por_no in candidatos:
            campo = resultado.afirmacao.campo
            alcance: Set[int] = set()
            for no in por_no:
                alcance |= {no, *indice.ancestors(no)}
            for ancestral in alcance:
                cobertura.setdefault(ancestral, set()).add(campo)

        minimo = min(len(candidatos),
                     max(config.minimo_campos_coesao,
                         ceil(config.coesao_minima * len(candidatos))))
        elegiveis = [no for no, cobertos in cobertura.items() if len(cobertos) >= minimo]
        if not elegiveis:
            elegiveis = list(cobertura)
        melhor = max(elegiveis,
                     key=lambda n: (indice.nodes[n].depth, len(cobertura[n]), -n))

        dentro: List[str] = []
        fora: List[str] = []
        for resultado, por_no in candidatos:
            escolhida = None
            for no, evidencias in por_no.items():
                if no == melhor or melhor in indice.ancestors(no):
                    escolhida = evidencias[0]
                    break
            if escolhida is None:
                fora.append(resultado.afirmacao.campo)
                continue
            if resultado.evidencias and resultado.evidencias[0] is not escolhida:
                resultado.evidencias.remove(escolhida)
                resultado.evidencias.insert(0, escolhida)
            dentro.append(resultado.afirmacao.campo)

        return Coesao(len(dentro) / len(candidatos), melhor,
                      indice.nodes[melhor].path, dentro, fora, True)

    # modo texto: sem árvore, resta a dispersão das linhas
    posicoes: Dict[str, int] = {}
    for resultado, _ in candidatos:
        ordem = base.order_of_evidence(resultado.evidencia_principal)
        if ordem is not None:
            posicoes[resultado.afirmacao.campo] = ordem
    if len(posicoes) < config.minimo_campos_coesao:
        return Coesao(1.0, None, "", list(posicoes), [], False)
    mediana = statistics.median(posicoes.values())
    dentro = [c for c, p in posicoes.items() if abs(p - mediana) <= config.janela_linhas_texto]
    fora = [c for c in posicoes if c not in dentro]
    return Coesao(len(dentro) / len(posicoes), None,
                  f"linhas ~{int(mediana)} ±{config.janela_linhas_texto}",
                  dentro, fora, True)


# ---------------------------------------------------------------------------
# Restrições de registro
# ---------------------------------------------------------------------------

def _classificar_precos(resultados: Sequence[ResultadoAfirmacao]
                        ) -> Tuple[List[Tuple[str, Decimal]], List[Tuple[str, Decimal]]]:
    atuais, antigos = [], []
    for resultado in resultados:
        afirmacao = resultado.afirmacao
        if afirmacao.tipo != "moeda" or not afirmacao.verificavel:
            continue
        valores = decimal_variants(afirmacao.valor)
        if not valores:
            continue
        valor = max(valores, key=abs)
        nome = normalize(afirmacao.campo)
        if any(termo in nome.split() or termo in nome for termo in _TERMOS_PRECO_ANTIGO):
            antigos.append((afirmacao.campo, valor))
        elif any(termo in nome for termo in _TERMOS_PRECO_ATUAL):
            atuais.append((afirmacao.campo, valor))
    return atuais, antigos


def avaliar_registro(registro: Registro, resultados: Sequence[ResultadoAfirmacao],
                     base: EvidenceBase, config: Config,
                     coesao: Coesao) -> List[ResultadoRestricao]:
    """Aplica as restrições internas de um registro."""
    saida: List[ResultadoRestricao] = []
    idx = registro.indice

    # R-PRECO-ORDEM ------------------------------------------------------
    atuais, antigos = _classificar_precos(resultados)
    if atuais and antigos:
        atual_campo, atual = min(atuais, key=lambda p: p[1])
        antigo_campo, antigo = max(antigos, key=lambda p: p[1])
        if atual > antigo:
            saida.append(ResultadoRestricao(
                "R-PRECO-ORDEM", "registro", VIOLADA, "alta",
                f"preço atual ({atual}) maior que o preço original ({antigo})",
                idx, [atual_campo, antigo_campo]))
        else:
            saida.append(ResultadoRestricao(
                "R-PRECO-ORDEM", "registro", OK, "alta",
                f"{atual} <= {antigo}", idx, [atual_campo, antigo_campo]))
    else:
        saida.append(ResultadoRestricao("R-PRECO-ORDEM", "registro", NAO_APLICAVEL,
                                        "alta", "registro sem par de preços", idx))

    # R-ANO-VS-DATA ------------------------------------------------------
    anos = [r for r in resultados if r.afirmacao.tipo == "ano" and r.afirmacao.verificavel]
    datas = [r for r in resultados if r.afirmacao.tipo == "data" and r.afirmacao.verificavel]
    if anos and datas:
        ano_valor = decimal_variants(anos[0].afirmacao.valor)
        data_valor = parse_date(datas[0].afirmacao.valor)
        if ano_valor and data_valor:
            declarado = int(max(ano_valor, key=abs))
            if declarado != data_valor.year:
                saida.append(ResultadoRestricao(
                    "R-ANO-VS-DATA", "registro", VIOLADA, "media",
                    f"ano declarado ({declarado}) difere do ano da data "
                    f"({data_valor.year})", idx,
                    [anos[0].afirmacao.campo, datas[0].afirmacao.campo]))
            else:
                saida.append(ResultadoRestricao("R-ANO-VS-DATA", "registro", OK,
                                                "media", "ano e data coerentes", idx))

    # R-QUANTIDADE-POSITIVA ----------------------------------------------
    zerados = []
    for resultado in resultados:
        if resultado.afirmacao.tipo != "inteiro" or not resultado.afirmacao.verificavel:
            continue
        valores = decimal_variants(resultado.afirmacao.valor)
        if valores and max(valores, key=abs) <= 0:
            zerados.append(resultado.afirmacao.campo)
    if zerados:
        saida.append(ResultadoRestricao(
            "R-QUANTIDADE-POSITIVA", "registro", VIOLADA, "media",
            "campo(s) de contagem com valor não positivo", idx, zerados))

    # R-RESUMO-TAMANHO ---------------------------------------------------
    for resultado in resultados:
        if not resultado.afirmacao.derivada:
            continue
        palavras = word_count(resultado.afirmacao.valor)
        if palavras > config.resumo_max_palavras:
            saida.append(ResultadoRestricao(
                "R-RESUMO-TAMANHO", "registro", VIOLADA, "baixa",
                f"'{resultado.afirmacao.campo}' com {palavras} palavras "
                f"(limite de {config.resumo_max_palavras} no prompt de extração)",
                idx, [resultado.afirmacao.campo]))
        else:
            saida.append(ResultadoRestricao(
                "R-RESUMO-TAMANHO", "registro", OK, "baixa",
                f"{palavras} palavras", idx, [resultado.afirmacao.campo]))

    # R-COESAO-DOM -------------------------------------------------------
    if not coesao.aplicavel:
        saida.append(ResultadoRestricao(
            "R-COESAO-DOM", "registro", NAO_APLICAVEL, "alta",
            "campos ancorados insuficientes para avaliar localidade", idx))
    elif coesao.campos_fora:
        saida.append(ResultadoRestricao(
            "R-COESAO-DOM", "registro", VIOLADA, "alta",
            f"coesão de {coesao.valor:.0%}: {', '.join(coesao.campos_fora)} "
            f"sem qualquer ocorrência na subárvore que ancora o registro "
            f"({coesao.caminho_ancora or '—'}); valores provenientes de outro item da página",
            idx, coesao.campos_fora))
    else:
        saida.append(ResultadoRestricao(
            "R-COESAO-DOM", "registro", OK, "alta",
            f"todos os {len(coesao.campos_ancorados)} campos ancorados em "
            f"{coesao.caminho_ancora or 'região única'}",
            idx, coesao.campos_ancorados))

    # R-REGISTRO-INFUNDADO ------------------------------------------------
    # Se a maioria dos campos verificáveis não existe na página, o próprio item
    # provavelmente não está lá: os poucos campos "ancorados" tendem a ser
    # coincidências lexicais (um título que aparece numa lista de relacionados).
    verificaveis = [r for r in resultados if r.veredito in Veredito.CONTABILIZADOS]
    reprovados = [r for r in verificaveis if r.veredito in Veredito.REPROVADOS]
    if len(verificaveis) >= 3 and len(reprovados) / len(verificaveis) > 0.5:
        saida.append(ResultadoRestricao(
            "R-REGISTRO-INFUNDADO", "registro", VIOLADA, "alta",
            f"{len(reprovados)}/{len(verificaveis)} campos verificáveis reprovados: "
            "o registro como um todo pode não corresponder a nenhum item da página",
            idx, [r.afirmacao.campo for r in reprovados]))

    # R-COMPLETUDE -------------------------------------------------------
    total = len(resultados)
    ausentes = [r.afirmacao.campo for r in resultados if r.afirmacao.abstencao]
    if total and len(ausentes) / total > 0.5:
        saida.append(ResultadoRestricao(
            "R-COMPLETUDE", "registro", VIOLADA, "baixa",
            f"{len(ausentes)}/{total} campos declarados indisponíveis", idx, ausentes))

    return saida


# ---------------------------------------------------------------------------
# Restrições de conjunto
# ---------------------------------------------------------------------------

def avaliar_conjunto(registros: Sequence[Registro],
                     resultados_por_registro: Sequence[Sequence[ResultadoAfirmacao]],
                     coesoes: Sequence[Coesao],
                     config: Config) -> List[ResultadoRestricao]:
    """Restrições que só fazem sentido sobre o conjunto extraído."""
    saida: List[ResultadoRestricao] = []
    if len(registros) < 2:
        return saida

    # R-REGISTROS-DUPLICADOS ---------------------------------------------
    assinaturas: Dict[str, List[int]] = {}
    for registro in registros:
        chave = "|".join(f"{k}={normalize(str(v))}" for k, v in sorted(registro.dados.items()))
        assinaturas.setdefault(chave, []).append(registro.indice)
    duplicados = [ids for ids in assinaturas.values() if len(ids) > 1]
    if duplicados:
        saida.append(ResultadoRestricao(
            "R-REGISTROS-DUPLICADOS", "conjunto", VIOLADA, "media",
            "registros idênticos repetidos: " +
            "; ".join("índices " + ", ".join(map(str, ids)) for ids in duplicados),
            None, []))
    else:
        saida.append(ResultadoRestricao("R-REGISTROS-DUPLICADOS", "conjunto", OK,
                                        "media", "nenhum registro repetido"))

    # R-VALOR-CONSTANTE ---------------------------------------------------
    campos: Dict[str, List[str]] = {}
    for registro in registros:
        for campo, valor in registro.dados.items():
            campos.setdefault(campo, []).append(normalize(str(valor)))
    constantes = []
    for campo, valores in campos.items():
        uteis = [v for v in valores if v and v not in ("nao disponivel", "n/a")]
        if len(uteis) >= 3 and len(set(uteis)) == 1:
            constantes.append(campo)
    if constantes:
        saida.append(ResultadoRestricao(
            "R-VALOR-CONSTANTE", "conjunto", VIOLADA, "media",
            "campo(s) com valor idêntico em todos os registros, indício de "
            "propagação do primeiro item: " + ", ".join(constantes), None, constantes))

    # R-ANCORAS-DISTINTAS -------------------------------------------------
    ancoras = [c.ancora for c in coesoes if c.ancora is not None]
    if len(ancoras) >= 2 and len(set(ancoras)) < len(ancoras):
        repetidas = {a for a in ancoras if ancoras.count(a) > 1}
        saida.append(ResultadoRestricao(
            "R-ANCORAS-DISTINTAS", "conjunto", VIOLADA, "media",
            f"{len(repetidas)} subárvore(s) do DOM ancoram mais de um registro: "
            "itens possivelmente duplicados a partir da mesma região da página"))
    elif ancoras:
        saida.append(ResultadoRestricao("R-ANCORAS-DISTINTAS", "conjunto", OK, "media",
                                        "cada registro ancorado em subárvore distinta"))
    return saida
