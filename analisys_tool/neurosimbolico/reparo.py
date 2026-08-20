"""
Reparo ancorado: proposta de correção para afirmações não suportadas.

A documentação prevê que as afirmações sejam "analisadas, verificadas e,
quando necessário, corrigidas de forma sistemática". Este módulo cobre a
última etapa, mas sem devolver o controle ao componente neural: as sugestões
são **extraídas da própria fonte**, restritas à subárvore que ancora o
registro, e cada uma vem acompanhada do caminho de onde foi retirada.

Nada é aplicado automaticamente: a correção só é gravada com `--aplicar-reparos`.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .config import Config, Veredito
from .dom import Chunk
from .evidencias import EvidenceBase
from .normalizacao import (
    content_tokens,
    decimal_variants,
    ean_valid,
    fold,
    isbn_valid,
    iter_numbers,
    normalize,
    parse_date,
)
from .predicados import ResultadoAfirmacao
from .restricoes import Coesao

__all__ = ["Sugestao", "sugerir_correcoes"]

_SEPARADOR_RE = re.compile(r"^\s*[:\-–—>]\s*")
_ISBN_CAND_RE = re.compile(r"(?:97[89][\s\-]?)?[\d][\d\s\-]{8,15}[\dxX]")


@dataclass
class Sugestao:
    """Candidato de correção extraído da fonte."""
    valor: str
    score: float
    caminho: str
    justificativa: str

    def to_dict(self) -> dict:
        return {"valor": self.valor, "score": round(self.score, 3),
                "caminho": self.caminho, "justificativa": self.justificativa}


def _pool(base: EvidenceBase, coesao: Coesao, limite: int = 400) -> List[Chunk]:
    """Chunks candidatos: subárvore do registro quando disponível."""
    indice = base.index
    if indice.structural and coesao.ancora is not None:
        chunks = indice.chunks_in_subtree(coesao.ancora)
        if len(chunks) >= 3:
            return chunks[:limite]
    return indice.chunks[:limite]


def _apos_rotulo(texto: str, rotulo: str) -> Optional[str]:
    """Retorna o trecho que segue o rótulo dentro do mesmo chunk."""
    posicao = fold(texto).find(fold(rotulo))
    if posicao == -1:
        return None
    resto = texto[posicao + len(rotulo):]
    resto = _SEPARADOR_RE.sub("", resto).strip()
    return resto or None


def _candidatos_por_rotulo(chunks: Sequence[Chunk], rotulos: Sequence[str]
                           ) -> List[tuple[str, Chunk, str]]:
    """Valores que aparecem imediatamente após um rótulo do campo."""
    saida: List[tuple[str, Chunk, str]] = []
    for posicao, chunk in enumerate(chunks):
        texto_norm = fold(chunk.text)
        for rotulo in rotulos:
            alvo = fold(rotulo)
            if len(alvo) < 3 or alvo not in texto_norm:
                continue
            resto = _apos_rotulo(chunk.text, rotulo)
            if resto:
                saida.append((resto, chunk, f"segue o rótulo '{rotulo}'"))
            elif posicao + 1 < len(chunks):
                proximo = chunks[posicao + 1]
                saida.append((proximo.text, proximo,
                              f"chunk seguinte ao rótulo '{rotulo}'"))
            break
    return saida


def _compativel(valor: str, tipo: str) -> bool:
    """Filtra candidatos incompatíveis com o tipo semântico do campo."""
    if not valor or len(valor) > 600:
        return False
    if tipo in ("moeda", "numero", "inteiro", "ano", "avaliacao"):
        valores = decimal_variants(valor)
        if not valores:
            return False
        if tipo == "ano":
            ano = int(max(valores, key=abs))
            return 1400 <= ano <= 2200
        return True
    if tipo == "isbn":
        return isbn_valid(valor) is not None
    if tipo == "ean":
        return ean_valid(valor) is not None
    if tipo == "url":
        return bool(re.match(r"^(https?://|www\.)", valor.strip(), re.I))
    if tipo == "email":
        return "@" in valor
    if tipo == "data":
        return parse_date(valor) is not None
    return True


def sugerir_correcoes(resultado: ResultadoAfirmacao, base: EvidenceBase,
                      coesao: Coesao, config: Config) -> List[Sugestao]:
    """
    Propõe até `config.sugestoes_por_campo` valores ancorados para uma
    afirmação não suportada.
    """
    if resultado.veredito not in Veredito.REPROVADOS:
        return []
    afirmacao = resultado.afirmacao
    if afirmacao.derivada:
        return []

    chunks = _pool(base, coesao)
    if not chunks:
        return []

    brutos: List[tuple[str, Chunk, str]] = _candidatos_por_rotulo(chunks, afirmacao.rotulos)

    tipo = afirmacao.tipo
    if tipo in ("moeda", "numero", "inteiro", "ano", "avaliacao"):
        for chunk in chunks:
            for occ in iter_numbers(fold(chunk.text)):
                fragmento = chunk.text[occ.start:occ.end]
                if tipo == "moeda" and not (occ.currency or "$" in chunk.text):
                    continue
                brutos.append((fragmento, chunk,
                               "valor numérico na subárvore do registro"))
    elif tipo in ("isbn", "ean"):
        for chunk in chunks:
            for achado in _ISBN_CAND_RE.finditer(chunk.text):
                candidato = achado.group(0).strip()
                verificador = isbn_valid(candidato) if tipo == "isbn" else ean_valid(candidato)
                if verificador:
                    brutos.append((candidato, chunk, "identificador com dígito verificador válido"))
    elif tipo == "url":
        for chunk in chunks:
            if chunk.kind == "attr:href" and re.match(r"^https?://", chunk.text, re.I):
                brutos.append((chunk.text, chunk, "destino de link na subárvore"))

    # -- pontuação e desduplicação ---------------------------------------
    vistos: Dict[str, Sugestao] = {}
    matcher = difflib.SequenceMatcher()
    matcher.set_seq2(normalize(afirmacao.valor))
    for valor, chunk, justificativa in brutos:
        valor = valor.strip()
        if not _compativel(valor, tipo):
            continue
        if normalize(valor) == normalize(afirmacao.valor):
            continue                       # é o próprio valor rejeitado
        score = 0.55
        if "rótulo" in justificativa:
            score += 0.30
        if chunk.kind.startswith("attr:"):
            score += 0.05
        matcher.set_seq1(normalize(valor))
        if matcher.real_quick_ratio() > 0.3:
            score += 0.15 * matcher.ratio()
        chave = normalize(valor)
        anterior = vistos.get(chave)
        if anterior is None or score > anterior.score:
            vistos[chave] = Sugestao(
                valor=valor, score=min(score, 0.99), caminho=chunk.path,
                justificativa=justificativa,
            )

    ordenadas = sorted(vistos.values(), key=lambda s: -s.score)
    return ordenadas[:config.sugestoes_por_campo]


def aplicar_reparos(registros: Sequence[dict],
                    sugestoes: Dict[str, List[Sugestao]]) -> List[dict]:
    """
    Gera uma cópia corrigida dos registros substituindo cada afirmação
    reprovada pela sugestão de maior score. Campos sem candidato ancorado
    são marcados como indisponíveis -- nunca mantidos com o valor alucinado.
    """
    corrigidos: List[dict] = []
    for indice, registro in enumerate(registros):
        copia = dict(registro)
        for campo in list(copia):
            chave = f"r{indice}:{campo}"
            if chave not in sugestoes:
                continue
            candidatos = sugestoes[chave]
            copia[campo] = candidatos[0].valor if candidatos else "Não disponível"
        corrigidos.append(copia)
    return corrigidos
