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
from .contexto import _aliases, _label_matches, vinculo_campo

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


def _pool(base: EvidenceBase, coesao: Coesao) -> List[Chunk]:
    """Somente uma entidade demonstrada pode fornecer valores de reparo."""
    indice = base.index
    if not coesao.aplicavel:
        return []
    if indice.structural:
        return (indice.chunks_in_subtree(coesao.ancora)
                if coesao.ancora is not None else [])
    return [indice.chunks[c] for c in coesao.chunks_ancora]


def _apos_rotulo(texto: str, rotulo: str) -> Optional[str]:
    """Retorna o trecho que segue o rótulo dentro do mesmo chunk."""
    match = re.search(r"(?<!\w)" + re.escape(fold(rotulo)) + r"\s*:\s*", fold(texto))
    if match is None:
        return None
    resto = re.split(r"[;|]|\s+[^\W\d_]+(?:[ \t]+[^\W\d_]+){0,3}\s*:",
                     texto[match.end():], maxsplit=1)[0].strip()
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

    # O léxico genérico de proximidade ("número", "total", "de", "por")
    # não basta para selecionar um atributo. Cada candidato precisa do
    # vínculo contextual usado na decisão factual.
    brutos: List[tuple[str, Chunk, str]] = []
    for chunk in chunks:
        if chunk.kind in {"attr:aria-label", "attr:title", "attr:placeholder"}:
            continue
        for rotulo in _aliases(resultado):
            valor = _apos_rotulo(chunk.text, rotulo)
            if valor:
                start = base._chunk_starts[chunk.cid] + fold(chunk.text).find(fold(valor))
                ev = base.make_evidence("REPARO-ROTULO", 1.0, start, start + len(valor))
                if vinculo_campo(resultado, ev, base, coesao.ancora) is True:
                    brutos.append((valor, chunk, f"valor após o rótulo '{rotulo}' na entidade"))
        # Valor em célula, <dd>, microdata ou após rótulo em nó separado.
        start = base._chunk_starts[chunk.cid]
        ev = base.make_evidence("REPARO-ATRIBUTO", 1.0, start, start + len(chunk.text))
        if (":" not in chunk.text and
                vinculo_campo(resultado, ev, base, coesao.ancora) is True):
            brutos.append((chunk.text, chunk, "rótulo estrutural do atributo na entidade"))

    tipo = afirmacao.tipo
    if tipo in ("moeda", "numero", "inteiro", "ano", "avaliacao"):
        for chunk in chunks:
            for occ in iter_numbers(fold(chunk.text)):
                fragmento = chunk.text[occ.start:occ.end]
                start = base._chunk_starts[chunk.cid] + occ.start
                ev = base.make_evidence("REPARO-NUMERO", 1.0, start,
                                        base._chunk_starts[chunk.cid] + occ.end)
                ev.unit = occ.unit
                if vinculo_campo(resultado, ev, base, coesao.ancora) is not True:
                    continue
                if occ.unit:
                    prefix = re.search(r"(?:r\$|us\$|\$|€|£|brl|usd|eur|gbp)\s*$",
                                       chunk.text[:occ.start], re.I)
                    suffix = re.match(r"\s*(?:r\$|us\$|\$|€|£|brl\b|usd\b|eur\b|gbp\b)",
                                      chunk.text[occ.end:], re.I)
                    if prefix:
                        fragmento = chunk.text[prefix.start():occ.end]
                    elif suffix:
                        fragmento = chunk.text[occ.start:occ.end + suffix.end()]
                brutos.append((fragmento, chunk,
                               "valor numérico com rótulo do atributo na entidade"))
    elif tipo in ("isbn", "ean"):
        for chunk in chunks:
            for achado in _ISBN_CAND_RE.finditer(chunk.text):
                candidato = achado.group(0).strip()
                verificador = isbn_valid(candidato) if tipo == "isbn" else ean_valid(candidato)
                start = base._chunk_starts[chunk.cid] + achado.start()
                ev = base.make_evidence("REPARO-ID", 1.0, start, start + len(candidato))
                if verificador and vinculo_campo(resultado, ev, base, coesao.ancora) is True:
                    brutos.append((candidato, chunk, "identificador com dígito verificador válido"))
    elif tipo == "url":
        for chunk in chunks:
            start = base._chunk_starts[chunk.cid]
            ev = base.make_evidence("REPARO-URL", 1.0, start, start + len(chunk.text))
            if (chunk.kind == "attr:href" and re.match(r"^https?://", chunk.text, re.I)
                    and vinculo_campo(resultado, ev, base, coesao.ancora) is True):
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
    # A similaridade com o erro não é critério factual para desempatar dois
    # valores conflitantes do mesmo atributo. Nesse caso, abster-se.
    if len(ordenadas) > 1:
        return []
    return ordenadas[:config.sugestoes_por_campo]


def aplicar_reparos(registros: Sequence[dict],
                    sugestoes: Dict[str, List[Sugestao]], schema=None) -> List[dict]:
    """
    Gera uma cópia corrigida dos registros substituindo cada afirmação
    reprovada pela sugestão de maior score. Campos sem candidato ancorado
    são marcados como indisponíveis -- nunca mantidos com o valor alucinado.
    """
    import copy
    from .afirmacoes import decompor
    from .contrato import ContractError, validate_records, loads_json
    from .normalizacao import decimal_variants

    corrigidos = copy.deepcopy(registros)
    por_chave = {a.id: a for r in decompor(registros, schema) for a in r.afirmacoes}
    for chave, candidatos in sugestoes.items():
        if chave not in por_chave:
            raise ContractError(f"Campo de reparo inexistente: {chave}")
        afirmacao = por_chave[chave]
        contrato = (schema or {}).get("items", {})
        pai = corrigidos[afirmacao.registro]
        for componente in afirmacao.caminho[:-1]:
            pai = pai[componente]
            contrato = contrato.get("items", {}) if isinstance(componente, int) else contrato.get("properties", {}).get(componente, {})
        ultimo = afirmacao.caminho[-1]
        contrato = contrato.get("items", {}) if isinstance(ultimo, int) else contrato.get("properties", {}).get(ultimo, {})
        tipos = contrato.get("type", [])
        tipos = [tipos] if isinstance(tipos, str) else tipos
        original = afirmacao.valor_bruto
        if not candidatos:
            if schema is None:
                valor = "Não disponível" if isinstance(original, str) else None
            elif "null" in tipos:
                valor = None
            else:
                raise ContractError("Contrato não permite abstenção nula; valor original preservado.")
        else:
            valor = candidatos[0].valor
            if type(original) in (int, float) or (schema and "string" not in tipos and set(tipos) & {"integer", "number"}):
                numeros = decimal_variants(valor)
                if len(numeros) != 1:
                    raise ContractError("Reparo numérico ambíguo.")
                numero = next(iter(numeros))
                integral = type(original) is int or "integer" in tipos and "number" not in tipos
                if integral and numero != numero.to_integral_value():
                    raise ContractError("Reparo fracionário para campo inteiro.")
                valor = int(numero) if integral else float(numero)
            elif type(original) is bool or (schema and set(tipos) <= {"boolean", "null"}):
                if normalize(valor) not in ("true", "false", "sim", "nao"):
                    raise ContractError("Reparo booleano ambíguo.")
                valor = normalize(valor) in ("true", "sim")
            elif schema and "string" not in tipos:
                valor = loads_json(valor)
        pai[ultimo] = valor
    if schema is not None:
        validate_records(corrigidos, schema)
    return corrigidos
