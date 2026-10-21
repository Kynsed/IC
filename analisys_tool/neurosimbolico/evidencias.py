"""
Base de evidências: recuperação determinística de suporte factual na fonte.

O índice de chunks produzido por `dom.py` é linearizado em um *fluxo*
normalizado (`flow`). Como `normalizacao.fold()` preserva comprimento, todo
offset no fluxo é convertido de volta para (chunk, posição no texto original),
o que permite anexar a cada veredito a citação exata que o sustenta.

Nenhuma etapa deste módulo consulta um modelo neural.
"""

from __future__ import annotations

import difflib
import re
from bisect import bisect_right
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from .dom import Chunk, SourceIndex
from .normalizacao import (
    NumberOccurrence,
    content_tokens,
    fold,
    iter_numbers,
    normalize,
    tokenize,
)

__all__ = ["Evidence", "EvidenceBase"]

MAX_FUZZY_CANDIDATES = 40


@dataclass
class Evidence:
    """Citação rastreável que sustenta (ou refuta) uma afirmação."""
    rule: str                      # identificador do predicado que a produziu
    score: float
    chunk_id: Optional[int]
    path: str                      # caminho no DOM / número da linha
    kind: str
    snippet_before: str = ""
    snippet_match: str = ""
    snippet_after: str = ""
    flow_start: int = -1
    flow_end: int = -1
    spans_chunks: int = 1
    detail: str = ""
    unit: Optional[str] = None
    negacao_externa: bool = False

    @property
    def snippet(self) -> str:
        return f"{self.snippet_before}[[{self.snippet_match}]]{self.snippet_after}".strip()

    def to_dict(self) -> dict:
        return {
            "regra": self.rule,
            "score": round(self.score, 4),
            "caminho": self.path,
            "tipo_no": self.kind,
            "trecho": self.snippet,
            "chunk": self.chunk_id,
            "detalhe": self.detail,
            "unidade": self.unit,
            "negacao_externa": self.negacao_externa,
        }


class EvidenceBase:
    """Consultas simbólicas sobre a fonte indexada."""

    def __init__(self, index: SourceIndex):
        self.index = index
        self.chunks: List[Chunk] = index.chunks

        # --- fluxo normalizado + mapa de offsets -----------------------------
        parts: List[str] = []
        self._chunk_starts: List[int] = []
        cursor = 0
        for chunk in self.chunks:
            self._chunk_starts.append(cursor)
            folded = fold(chunk.text)          # preserva comprimento
            parts.append(folded)
            cursor += len(folded) + 1          # separador de 1 caractere
        self.flow: str = " ".join(parts)

        # --- índices auxiliares ---------------------------------------------
        self._token_positions: Dict[str, List[int]] = {}
        for match in re.finditer(r"[^\W_]+", self.flow, re.UNICODE):
            self._token_positions.setdefault(match.group(0), []).append(match.start())
        self.token_set: Set[str] = set(self._token_positions)

        self._chunk_tokens: List[Set[str]] = [set(tokenize(c.text)) for c in self.chunks]
        self._inverted: Dict[str, List[int]] = {}
        for cid, tokens in enumerate(self._chunk_tokens):
            for tok in tokens:
                self._inverted.setdefault(tok, []).append(cid)

        self.numbers: List[NumberOccurrence] = list(iter_numbers(self.flow))
        self._numbers_by_value: Dict[Decimal, List[int]] = {}
        for pos, occ in enumerate(self.numbers):
            for value in occ.values:
                self._numbers_by_value.setdefault(value, []).append(pos)

    # ------------------------------------------------------------------
    # Mapeamento fluxo -> fonte
    # ------------------------------------------------------------------

    def chunk_at(self, flow_offset: int) -> Optional[Chunk]:
        if not self.chunks:
            return None
        pos = bisect_right(self._chunk_starts, flow_offset) - 1
        return self.chunks[max(0, pos)]

    def _spans(self, start: int, end: int) -> int:
        first = bisect_right(self._chunk_starts, start) - 1
        last = bisect_right(self._chunk_starts, max(start, end - 1)) - 1
        return max(1, last - first + 1)

    def make_evidence(self, rule: str, score: float, start: int, end: int,
                      detail: str = "", context: int = 45) -> Evidence:
        """Converte um casamento no fluxo em citação do texto original."""
        chunk = self.chunk_at(start)
        if chunk is None:
            return Evidence(rule=rule, score=score, chunk_id=None, path="?", kind="?",
                            flow_start=start, flow_end=end, detail=detail)
        local = start - self._chunk_starts[chunk.cid]
        length = end - start
        text = chunk.text
        local = max(0, min(local, len(text)))
        match_text = text[local:local + length]
        if len(match_text) < length:                     # casamento cruzou chunks
            match_text = (match_text + " " + self.flow[start + len(match_text):end]).strip()
        prefix = re.split(r"[.!?;:]", fold(text[:local]))[-1]
        negated = bool(re.search(
            r"\b(?:nao|nunca|jamais|not|never|sem|without)\b(?:\s+\w+){0,3}\s*$", prefix))
        return Evidence(
            rule=rule, score=score, chunk_id=chunk.cid, path=chunk.path, kind=chunk.kind,
            snippet_before=("…" if local > context else "") + text[max(0, local - context):local],
            snippet_match=match_text,
            snippet_after=text[local + length:local + length + context] +
                          ("…" if len(text) > local + length + context else ""),
            flow_start=start, flow_end=end, spans_chunks=self._spans(start, end),
            detail=detail,
            negacao_externa=negated,
        )

    # ------------------------------------------------------------------
    # Busca lexical
    # ------------------------------------------------------------------

    def find_literal(self, value: str, rule: str = "LEX-EXATO") -> List[Evidence]:
        """Ocorrências literais (após normalização) do valor na fonte."""
        needle = normalize(value)
        if not needle:
            return []
        out: List[Evidence] = []
        pattern = (r"(?<!\w)" if needle[0].isalnum() else "") + re.escape(needle)
        pattern += r"(?!\w)" if needle[-1].isalnum() else ""
        for match in re.finditer(pattern, self.flow):
            if self._same_region(match.start(), match.end()):
                out.append(self.make_evidence(rule, 1.0, match.start(), match.end()))
        return out

    def _same_region(self, start: int, end: int) -> bool:
        """Não transformar concatenação de itens/atributos em citação literal."""
        first, last = self.chunk_at(start), self.chunk_at(max(start, end - 1))
        if first is None or last is None or first.cid == last.cid:
            return True
        if not self.index.structural:
            return True  # quebras de linha de texto podem ser apenas diagramação
        chunks = self.chunks[first.cid:last.cid + 1]
        if any(c.kind.startswith("attr:") for c in chunks):
            return False
        blocks = {"article", "section", "li", "tr", "td", "th", "p", "dd", "dt",
                  "h1", "h2", "h3", "h4", "h5", "h6", "div"}
        def block(chunk):
            for no in [chunk.node, *self.index.ancestors(chunk.node)]:
                if self.index.nodes[no].tag in blocks:
                    return no
            return 0
        return len({block(c) for c in chunks}) == 1

    def find_loose(self, value: str, rule: str = "LEX-TOLERANTE") -> List[Evidence]:
        """
        Casamento tolerante a separadores, nos dois sentidos: aceita variações
        de pontuação e espaçamento tanto no valor afirmado quanto no texto da
        página ("9788582850350" ~ "978-85-8285-035-0", "R$69,90" ~ "R$ 90").

        Identificadores longos (8+ dígitos) são flexibilizados caractere a
        caractere, pois é neles que a página costuma inserir hífens.
        """
        tokens = tokenize(value)
        if not tokens or len(tokens) > 60:
            return []
        partes = []
        for tok in tokens:
            if tok.isdigit() and len(tok) >= 8:
                partes.append(r"[\W_]{0,3}".join(re.escape(d) for d in tok))
            else:
                partes.append(re.escape(tok))
        pattern = r"(?<!\w)" + r"[\W_]{0,4}".join(partes) + r"(?!\w)"
        out: List[Evidence] = []
        for match in re.finditer(pattern, self.flow):
            if self._same_region(match.start(), match.end()):
                out.append(self.make_evidence(rule, 0.95, match.start(), match.end()))
        return out

    def find_regex(self, pattern: str, rule: str, score: float = 0.9) -> List[Evidence]:
        out: List[Evidence] = []
        for match in re.finditer(pattern, self.flow):
            if self._same_region(match.start(), match.end()):
                out.append(self.make_evidence(rule, score, match.start(), match.end()))
        return out

    # ------------------------------------------------------------------
    # Busca numérica
    # ------------------------------------------------------------------

    def find_numeric(self, values: Iterable[Decimal],
                     rule: str = "NUM-IGUAL") -> List[Evidence]:
        """Ocorrências numericamente equivalentes ao valor afirmado."""
        seen: Set[int] = set()
        out: List[Evidence] = []
        for value in values:
            for pos in self._numbers_by_value.get(value, ()):
                if pos in seen:
                    continue
                seen.add(pos)
                occ = self.numbers[pos]
                evidence = self.make_evidence(rule, 1.0, occ.start, occ.end,
                                              detail="com símbolo monetário" if occ.currency else "")
                evidence.spans_chunks = 1
                evidence.unit = occ.unit
                out.append(evidence)
        return sorted(out, key=lambda e: e.flow_start)

    def numbers_present(self, values: Iterable[Decimal]) -> bool:
        return any(value in self._numbers_by_value for value in values)

    def novel_numbers(self, text: str) -> List[str]:
        """Números citados no valor que não existem em lugar algum da fonte."""
        out: List[str] = []
        for occ in iter_numbers(normalize(text)):
            if not any(value in self._numbers_by_value for value in occ.values):
                out.append(occ.raw)
        return out

    # ------------------------------------------------------------------
    # Proximidade de rótulo
    # ------------------------------------------------------------------

    def label_near(self, start: int, end: int, labels: Iterable[str],
                   window: int = 140) -> Optional[str]:
        """
        Verifica se algum token de rótulo do campo ocorre nas vizinhanças do
        casamento. Um número solto na página é evidência fraca; o mesmo número
        precedido de "Preço:" é evidência forte.
        """
        for label in labels:
            for tok in tokenize(label):
                for pos in self._token_positions.get(tok, ()):
                    if start - window <= pos <= end + window // 2:
                        return label
        return None

    # ------------------------------------------------------------------
    # Cobertura lexical (campos longos)
    # ------------------------------------------------------------------

    def coverage(self, text: str) -> Tuple[float, List[str]]:
        """Fração dos tokens de conteúdo presentes em qualquer ponto da fonte."""
        tokens = set(content_tokens(text))
        if not tokens:
            return 1.0, []
        missing = sorted(tok for tok in tokens if tok not in self.token_set)
        return (len(tokens) - len(missing)) / len(tokens), missing

    def best_window(self, text: str) -> Tuple[float, Optional[Evidence]]:
        """
        Melhor região contígua da fonte que concentra os tokens do valor.

        Evita o falso positivo de um texto longo "coberto" por tokens espalhados
        por toda a página: exige concentração em uma janela local.
        """
        tokens = set(content_tokens(text))
        if not tokens:
            return 0.0, None
        events: List[Tuple[int, str]] = []
        for tok in tokens:
            for pos in self._token_positions.get(tok, ())[:400]:
                events.append((pos, tok))
        if not events:
            return 0.0, None
        events.sort()
        span = max(240, int(len(normalize(text)) * 1.6))
        counter: Dict[str, int] = {}
        best_count, best_range = 0, (events[0][0], events[0][0])
        left = 0
        for right, (pos, tok) in enumerate(events):
            counter[tok] = counter.get(tok, 0) + 1
            while events[right][0] - events[left][0] > span:
                dropped = events[left][1]
                counter[dropped] -= 1
                if counter[dropped] == 0:
                    del counter[dropped]
                left += 1
            if len(counter) > best_count:
                best_count = len(counter)
                best_range = (events[left][0], events[right][0])
        ratio = best_count / len(tokens)
        evidence = self.make_evidence(
            "LEX-COBERTURA", ratio, best_range[0], min(best_range[1] + 24, len(self.flow)),
            detail=f"{best_count}/{len(tokens)} tokens de conteúdo na mesma região",
        )
        return ratio, evidence

    # ------------------------------------------------------------------
    # Similaridade aproximada
    # ------------------------------------------------------------------

    def best_fuzzy(self, value: str) -> Tuple[float, Optional[Evidence]]:
        """Chunk mais similar ao valor afirmado (difflib, determinístico)."""
        needle = normalize(value)
        if not needle:
            return 0.0, None
        tokens = content_tokens(value) or tokenize(value)
        scores: Dict[int, int] = {}
        for tok in tokens:
            for cid in self._inverted.get(tok, ())[:600]:
                scores[cid] = scores.get(cid, 0) + 1
        if not scores:
            return 0.0, None
        candidates = sorted(scores, key=lambda c: -scores[c])[:MAX_FUZZY_CANDIDATES]
        matcher = difflib.SequenceMatcher()
        matcher.set_seq2(needle)
        best_ratio, best_cid = 0.0, None
        for cid in candidates:
            matcher.set_seq1(fold(self.chunks[cid].text))
            if matcher.real_quick_ratio() <= best_ratio:
                continue
            ratio = matcher.ratio()
            if ratio > best_ratio:
                best_ratio, best_cid = ratio, cid
        if best_cid is None:
            return 0.0, None
        start = self._chunk_starts[best_cid]
        evidence = self.make_evidence(
            "LEX-APROXIMADO", best_ratio, start,
            start + min(len(self.chunks[best_cid].text), 160),
            detail=f"similaridade {best_ratio:.2f}",
        )
        return best_ratio, evidence

    # ------------------------------------------------------------------
    # Localidade estrutural
    # ------------------------------------------------------------------

    def node_of_evidence(self, evidence: Evidence) -> Optional[int]:
        if evidence.chunk_id is None:
            return None
        return self.chunks[evidence.chunk_id].node

    def order_of_evidence(self, evidence: Evidence) -> Optional[int]:
        if evidence.chunk_id is None:
            return None
        return self.chunks[evidence.chunk_id].order
