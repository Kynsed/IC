"""
Camada de normalização determinística do pipeline neuro-simbólico.

Todas as funções deste módulo são puras e determinísticas: não dependem de
modelos neurais, não usam aleatoriedade e produzem sempre o mesmo resultado
para a mesma entrada. Elas formam a base sobre a qual os predicados simbólicos
de verificação são construídos.

Requisito de projeto importante: `fold()` preserva o comprimento da string.
Isso garante que qualquer casamento (match) encontrado sobre o texto normalizado
possa ser mapeado de volta, caractere a caractere, para o texto original --
condição necessária para a rastreabilidade exigida pela verificação factual.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterator, List, NamedTuple, Optional, Sequence, Set

__all__ = [
    "clean_whitespace",
    "fold",
    "normalize",
    "tokenize",
    "content_tokens",
    "word_count",
    "parse_decimal",
    "decimal_variants",
    "iter_numbers",
    "NumberOccurrence",
    "parse_date",
    "date_renderings",
    "isbn_valid",
    "ean_valid",
    "looks_like_html",
    "is_abstention",
    "is_extraction_error",
    "STOPWORDS",
]

# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------

_SPACE_MAP = {
    "\xa0": " ",   # nbsp
    " ": " ",
    " ": " ",
    " ": " ",
    "​": " ",  # zero-width space -> espaço (preserva comprimento)
    "﻿": " ",
}
_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

# Stopwords PT/EN usadas apenas em métricas de cobertura lexical.
STOPWORDS: Set[str] = {
    # português
    "a", "as", "ao", "aos", "à", "às", "o", "os", "um", "uma", "uns", "umas",
    "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas", "por",
    "pelo", "pela", "para", "com", "sem", "sob", "sobre", "entre", "e", "ou",
    "que", "se", "sua", "seu", "suas", "seus", "este", "esta", "esse", "essa",
    "isso", "aquele", "aquela", "como", "mais", "menos", "muito", "ja", "nao",
    "foi", "ser", "sao", "era", "tem", "ate", "apos", "onde", "quando", "qual",
    # inglês
    "the", "of", "and", "or", "to", "in", "on", "at", "for", "with", "without",
    "by", "from", "as", "is", "are", "was", "were", "be", "been", "it", "its",
    "this", "that", "these", "those", "an", "a",
}


def clean_whitespace(text: str) -> str:
    """Colapsa espaços em branco e normaliza espaços especiais (nbsp, zwsp...)."""
    if not text:
        return ""
    for src, dst in _SPACE_MAP.items():
        if src in text:
            text = text.replace(src, dst)
    return _WS_RE.sub(" ", text).strip()


def fold(text: str) -> str:
    """
    Minúsculas + remoção de acentos **preservando o comprimento da string**.

    A decomposição NFKD é aplicada caractere a caractere; se ela expandir o
    caractere (ligaduras, frações etc.) o original é mantido, de modo que
    `len(fold(s)) == len(s)` sempre. Isso mantém os offsets alinhados entre o
    texto normalizado (usado na busca) e o texto original (usado na evidência).
    """
    out: List[str] = []
    for ch in text:
        dec = unicodedata.normalize("NFKD", ch)
        dec = "".join(c for c in dec if not unicodedata.combining(c))
        if len(dec) != 1:
            dec = ch
        low = dec.lower()
        if len(low) != 1:
            low = dec
        out.append(low)
    return "".join(out)


def normalize(text: str) -> str:
    """Forma canônica usada nas buscas: espaços colapsados + fold()."""
    return fold(clean_whitespace(text))


def tokenize(text: str) -> List[str]:
    """Tokens alfanuméricos do texto normalizado."""
    return _TOKEN_RE.findall(normalize(text))


def content_tokens(text: str, min_len: int = 2) -> List[str]:
    """Tokens de conteúdo: sem stopwords e com comprimento mínimo (dígitos sempre entram)."""
    out = []
    for tok in tokenize(text):
        if tok in STOPWORDS:
            continue
        if len(tok) < min_len and not tok.isdigit():
            continue
        out.append(tok)
    return out


def word_count(text: str) -> int:
    return len(clean_whitespace(text).split()) if text else 0


# ---------------------------------------------------------------------------
# Números
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"(?<![\w])[+-]?\d(?:[\d.,]*\d)?")
_CURRENCY_HINT_RE = re.compile(r"(r\$|us\$|\$|€|£|brl|usd|eur|gbp)\s*$", re.I)
_CURRENCY_CODES = {"r$": "BRL", "brl": "BRL", "us$": "USD", "usd": "USD",
                   "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP", "$": "DOLLAR"}
_NUM_LITERAL_RE = re.compile(
    r"\s*(?:(?:r\$|us\$|\$|€|£|brl|usd|eur|gbp)\s*)?"
    r"([+-]?\d(?:[\d.,]*\d)?)"
    r"\s*(?:(?:r\$|us\$|\$|€|£|brl|usd|eur|gbp))?\s*", re.I)


def currency_code(raw: str) -> Optional[str]:
    """Unidade declarada; '$' sozinho permanece ambíguo, sem assumir USD."""
    found = re.search(r"r\$|us\$|\$|€|£|\b(?:brl|usd|eur|gbp)\b", raw, re.I)
    return _CURRENCY_CODES[found.group().lower()] if found else None


class NumberOccurrence(NamedTuple):
    """Ocorrência numérica localizada no texto-fonte."""
    values: frozenset          # interpretações possíveis (Decimal)
    start: int
    end: int
    raw: str
    currency: bool
    unit: Optional[str] = None


def _strip_to_numeric(raw: str) -> str:
    # Um valor deve conter exatamente um literal; remover letras juntava
    # "10 ou 20" em 1020 e criava um fato que não foi afirmado.
    text = clean_whitespace(str(raw))
    units = {_CURRENCY_CODES[m.lower()] for m in re.findall(
        r"r\$|us\$|\$|€|£|\b(?:brl|usd|eur|gbp)\b", text, re.I)}
    if len(units) > 1:
        return ""
    match = _NUM_LITERAL_RE.fullmatch(text)
    return match.group(1) if match else ""


def decimal_variants(raw: str) -> Set[Decimal]:
    """
    Todas as leituras plausíveis de um literal numérico.

    "R$ 1.234,56" -> {1234.56}          (não ambíguo: dois separadores)
    "1.234"       -> {1234, 1.234}      (ambíguo pt-BR/en-US)
    "69,69"       -> {69.69}            (grupo != 3 dígitos => decimal)
    """
    s = _strip_to_numeric(raw)
    if not s:
        return set()
    neg = s.startswith("-")
    s = s.lstrip("+-")
    if not s or not any(c.isdigit() for c in s):
        return set()

    candidates: Set[str] = set()
    has_comma, has_dot = "," in s, "." in s

    if has_comma and has_dot:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        integer, fractional = s.rsplit(dec, 1)
        groups = integer.split(thou)
        if (not fractional.isdigit() or dec in integer or
                not (1 <= len(groups[0]) <= 3) or
                not all(len(p) == 3 and p.isdigit() for p in groups[1:])):
            return set()
        candidates.add(s.replace(thou, "").replace(dec, "."))
    elif has_comma or has_dot:
        sep = "," if has_comma else "."
        parts = s.split(sep)
        # separador de milhar: todos os grupos após o primeiro têm 3 dígitos
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
            candidates.add(s.replace(sep, ""))
        if len(parts) == 2:
            candidates.add(s.replace(sep, "."))
    else:
        candidates.add(s)

    out: Set[Decimal] = set()
    for cand in candidates:
        try:
            value = Decimal(cand)
        except (InvalidOperation, ValueError):
            continue
        out.add(-value if neg else value)
    return out


def parse_decimal(raw: str) -> Optional[Decimal]:
    """Interpretação principal (a de maior magnitude, i.e. separador de milhar)."""
    variants = decimal_variants(raw)
    if not variants:
        return None
    return max(variants, key=abs)


def iter_numbers(text: str) -> Iterator[NumberOccurrence]:
    """Percorre todas as ocorrências numéricas de `text` (já normalizado)."""
    for m in _NUM_RE.finditer(text):
        raw = m.group(0).rstrip(".,")
        if not raw or not any(c.isdigit() for c in raw):
            continue
        values = decimal_variants(raw)
        if not values:
            continue
        start = m.start()
        prefix = text[max(0, start - 8):start]
        hint = _CURRENCY_HINT_RE.search(prefix)
        suffix = re.match(r"\s*(r\$|us\$|\$|€|£|brl\b|usd\b|eur\b|gbp\b)",
                          text[start + len(raw):], re.I)
        unit = currency_code(hint.group()) if hint else (currency_code(suffix.group()) if suffix else None)
        yield NumberOccurrence(
            values=frozenset(values),
            start=start,
            end=start + len(raw),
            raw=raw,
            currency=bool(hint or suffix),
            unit=unit,
        )


# ---------------------------------------------------------------------------
# Datas
# ---------------------------------------------------------------------------

_MONTHS = {
    "janeiro": 1, "jan": 1, "january": 1,
    "fevereiro": 2, "fev": 2, "feb": 2, "february": 2,
    "marco": 3, "mar": 3, "march": 3,
    "abril": 4, "abr": 4, "apr": 4, "april": 4,
    "maio": 5, "mai": 5, "may": 5,
    "junho": 6, "jun": 6, "june": 6,
    "julho": 7, "jul": 7, "july": 7,
    "agosto": 8, "ago": 8, "aug": 8, "august": 8,
    "setembro": 9, "set": 9, "sep": 9, "sept": 9, "september": 9,
    "outubro": 10, "out": 10, "oct": 10, "october": 10,
    "novembro": 11, "nov": 11, "november": 11,
    "dezembro": 12, "dez": 12, "dec": 12, "december": 12,
}
_DATE_NUM_RE = re.compile(r"(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{1,4})")
_DATE_EXT_RE = re.compile(r"(\d{1,2})\s*(?:de\s+)?([a-z]{3,9})\.?\s*(?:de\s+|,\s*)?(\d{4})")
_DATE_EXT_EN_RE = re.compile(r"([a-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})")


def parse_date(value: str) -> Optional[date]:
    """Interpreta uma data em formatos numéricos e por extenso (pt/en)."""
    if not value:
        return None
    text = normalize(value)

    m = _DATE_NUM_RE.search(text)
    if m:
        a, b, c = (int(g) for g in m.groups())
        for day, month, year in ((a, b, c), (c, b, a)):
            if year > 31:
                try:
                    return date(year if year > 99 else 2000 + year, month, day)
                except ValueError:
                    continue

    m = _DATE_EXT_RE.search(text)
    if m and m.group(2) in _MONTHS:
        try:
            return date(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
        except ValueError:
            return None

    m = _DATE_EXT_EN_RE.search(text)
    if m and m.group(1) in _MONTHS:
        try:
            return date(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2)))
        except ValueError:
            return None
    return None


_MONTHS_PT = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
              "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def date_renderings(value: date) -> List[str]:
    """Formas textuais equivalentes de uma data, para busca na página."""
    return [
        value.strftime("%d/%m/%Y"),
        value.strftime("%d-%m-%Y"),
        value.strftime("%Y-%m-%d"),
        f"{value.day}/{value.month}/{value.year}",
        f"{value.day} de {_MONTHS_PT[value.month]} de {value.year}",
        f"{_MONTHS_PT[value.month]} {value.day}, {value.year}",
    ]


# ---------------------------------------------------------------------------
# Identificadores com dígito verificador
# ---------------------------------------------------------------------------

def isbn_valid(value: str) -> Optional[bool]:
    """
    Valida o dígito verificador de um ISBN-10/13.

    Retorna None quando a string não tem forma de ISBN (verificação
    não aplicável) -- distinção importante para não confundir
    "valor mal formado" com "valor não verificável".
    """
    digits = re.sub(r"[^0-9xX]", "", value or "")
    if len(digits) == 10:
        total = 0
        for i, ch in enumerate(digits):
            v = 10 if ch in "xX" else int(ch)
            total += v * (10 - i)
        return total % 11 == 0
    if len(digits) == 13:
        return ean_valid(digits) is True
    return None


def ean_valid(value: str) -> Optional[bool]:
    """Valida o dígito verificador de EAN-8/13 (GTIN)."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) not in (8, 13):
        return None
    total = 0
    for i, ch in enumerate(reversed(digits[:-1]), start=1):
        total += int(ch) * (3 if i % 2 == 1 else 1)
    return (10 - total % 10) % 10 == int(digits[-1])


# ---------------------------------------------------------------------------
# Heurísticas de classificação de entrada
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<(?:!doctype|html|body|div|span|p|a|h[1-6]|table|ul|li|meta)\b", re.I)

_ABSTENTION_VALUES = {
    "", "-", "--", "n/a", "na", "nao disponivel", "não disponível",
    "nao informado", "não informado", "not available", "none", "null",
    "sem informacao", "sem informação", "indisponivel", "indisponível",
    "nao encontrado", "não encontrado", "not found", "desconhecido",
}
_ERROR_VALUES = {"erro na extracao", "erro na api", "erro"}


def looks_like_html(text: str) -> bool:
    """Distingue o HTML bruto do texto já limpo salvo pelo extraction_tool."""
    return bool(_HTML_TAG_RE.search(text[:20000]) or
                re.search(r"<(?:article|section|tr|td|dl|dt|dd)\b", text[:20000], re.I))


def is_abstention(value) -> bool:
    """True quando o LLM declarou ausência do dado (abstenção, não alucinação)."""
    if value is None:
        return True
    text = normalize(str(value)).strip(" .")
    return text in _ABSTENTION_VALUES


def is_extraction_error(value) -> bool:
    """True para os marcadores de falha emitidos pelo extraction_tool."""
    if value is None:
        return False
    text = normalize(str(value)).strip(" .")
    return text in _ERROR_VALUES or text.startswith("erro na api")
