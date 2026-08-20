"""
Decomposição da saída do LLM em afirmações atômicas verificáveis.

Cada registro produzido pelo `extraction_tool` (um objeto JSON campo -> valor)
é convertido em um conjunto de `Afirmacao`. A verificação simbólica opera
sobre afirmações atômicas, não sobre o registro inteiro: é isso que permite
localizar *qual* campo alucinou, e não apenas dizer que a extração falhou.

O tipo de cada afirmação é inferido de forma determinística, primeiro pelo
nome do campo (léxico PT/EN) e depois pela forma do valor.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .normalizacao import (
    is_abstention,
    is_extraction_error,
    normalize,
    parse_date,
    parse_decimal,
    tokenize,
    word_count,
)

__all__ = ["Afirmacao", "Registro", "carregar_registros", "decompor"]

# ---------------------------------------------------------------------------
# Léxico de campos: nome do campo -> tipo semântico
# ---------------------------------------------------------------------------

CAMPO_TIPOS: Dict[str, Sequence[str]] = {
    "moeda": ("preco", "preço", "price", "valor", "custo", "cost", "amount",
              "preco atual", "preco antigo", "preco original", "preco promocional"),
    "inteiro": ("paginas", "páginas", "pages", "quantidade", "qtd", "estoque",
                "stock", "unidades", "numero de paginas", "número de páginas"),
    "ano": ("ano", "year", "ano de publicacao", "ano de publicação",
            "ano de lancamento", "ano de lançamento"),
    "isbn": ("isbn", "isbn10", "isbn13", "isbn-10", "isbn-13"),
    "ean": ("ean", "gtin", "upc", "codigo de barras", "código de barras"),
    "url": ("url", "link", "endereco", "endereço", "site", "pagina", "página"),
    "email": ("email", "e-mail", "correio eletronico"),
    "data": ("data", "date", "data de publicacao", "data de publicação",
             "lancamento", "lançamento", "publicado em", "validade"),
    "avaliacao": ("avaliacao", "avaliação", "nota", "rating", "estrelas", "score"),
    "texto_longo": ("descricao", "descrição", "description", "detalhes", "details",
                    "sinopse", "resumo", "summary", "conteudo", "conteúdo",
                    "observacoes", "observações"),
}

# Campos derivados de outro campo do mesmo registro (não da página).
# O extraction_tool acrescenta 'Resumo' como condensação da 'Descrição';
# verificá-lo contra a página seria incorreto -- a base factual é a descrição.
CAMPOS_DERIVADOS: Dict[str, Sequence[str]] = {
    "resumo": ("descricao", "descrição", "description", "detalhes", "details", "sinopse"),
    "summary": ("description", "details", "descricao", "descrição"),
}

# Rótulos adicionais procurados na página ao avaliar proximidade.
SINONIMOS_ROTULO: Dict[str, Sequence[str]] = {
    "moeda": ("preço", "preco", "price", "valor", "por", "de", "r$"),
    "inteiro": ("quantidade", "número", "numero", "total"),
    "ano": ("ano", "publicação", "publicacao", "edição", "edicao", "year"),
    "isbn": ("isbn", "código", "codigo"),
    "ean": ("ean", "gtin", "código de barras"),
    "data": ("data", "publicado", "lançamento", "lancamento"),
    "avaliacao": ("avaliação", "avaliacao", "nota", "estrelas", "rating"),
}

_URL_RE = re.compile(r"^(https?://|www\.)\S+$", re.I)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
_ISBN_RE = re.compile(r"^(97[89])?[\d\-\s]{9,17}[\dxX]$")
_NUM_ONLY_RE = re.compile(r"^[\s\-+]?[\d.,]+$")
_MOEDA_RE = re.compile(r"(r\$|us\$|\$|€|£|brl|usd|eur)", re.I)

LIMIAR_TEXTO_LONGO = 18   # palavras


@dataclass
class Afirmacao:
    """Uma afirmação atômica: (registro, campo) = valor."""
    registro: int
    campo: str
    valor: str
    tipo: str
    rotulos: List[str] = field(default_factory=list)
    base_derivacao: Optional[str] = None     # campo-base, quando derivado
    valor_base: Optional[str] = None
    abstencao: bool = False
    erro_extracao: bool = False

    @property
    def id(self) -> str:
        return f"r{self.registro}:{self.campo}"

    @property
    def verificavel(self) -> bool:
        return not (self.abstencao or self.erro_extracao)

    @property
    def derivada(self) -> bool:
        return self.base_derivacao is not None and bool(self.valor_base)


@dataclass
class Registro:
    """Um item extraído (uma linha da tabela de resultados)."""
    indice: int
    dados: Dict[str, Any]
    afirmacoes: List[Afirmacao] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Inferência de tipo
# ---------------------------------------------------------------------------

def _tipo_por_nome(campo: str) -> Optional[str]:
    nome = normalize(campo)
    for tipo, chaves in CAMPO_TIPOS.items():
        for chave in chaves:
            chave_norm = normalize(chave)
            if nome == chave_norm:
                return tipo
    for tipo, chaves in CAMPO_TIPOS.items():
        for chave in chaves:
            chave_norm = normalize(chave)
            if chave_norm and (chave_norm in nome or nome in chave_norm):
                return tipo
    return None


def _tipo_por_valor(valor: str) -> str:
    texto = valor.strip()
    if _URL_RE.match(texto):
        return "url"
    if _EMAIL_RE.match(texto):
        return "email"
    if _MOEDA_RE.search(texto) and any(c.isdigit() for c in texto):
        return "moeda"
    digitos = re.sub(r"[^0-9xX]", "", texto)
    if _ISBN_RE.match(texto) and len(digitos) in (10, 13):
        return "isbn"
    if _NUM_ONLY_RE.match(texto):
        numero = parse_decimal(texto)
        if numero is not None:
            if numero == numero.to_integral_value():
                inteiro = int(numero)
                if 1400 <= inteiro <= 2200 and len(re.sub(r"\D", "", texto)) == 4:
                    return "ano"
                return "inteiro"
            return "numero"
    if parse_date(texto) is not None and len(texto) <= 40:
        return "data"
    if word_count(texto) >= LIMIAR_TEXTO_LONGO:
        return "texto_longo"
    return "texto"


def inferir_tipo(campo: str, valor: str) -> str:
    """Tipo semântico da afirmação: nome do campo tem prioridade sobre a forma."""
    por_nome = _tipo_por_nome(campo)
    por_valor = _tipo_por_valor(valor)
    if por_nome is None:
        return por_valor
    # O nome define a intenção, mas um valor claramente textual em campo
    # numérico não deve ser tratado como número (evita falso 'INVALIDO').
    if por_nome in ("moeda", "inteiro", "ano", "numero") and por_valor in ("texto", "texto_longo"):
        if not any(c.isdigit() for c in valor):
            return "texto"
    if por_nome == "texto_longo" and word_count(valor) < LIMIAR_TEXTO_LONGO:
        return "texto"
    return por_nome


def _rotulos(campo: str, tipo: str) -> List[str]:
    rotulos = [campo]
    rotulos.extend(SINONIMOS_ROTULO.get(tipo, ()))
    vistos, saida = set(), []
    for rotulo in rotulos:
        chave = normalize(rotulo)
        if chave and chave not in vistos:
            vistos.add(chave)
            saida.append(rotulo)
    return saida


def _campo_base(campo: str, dados: Dict[str, Any]) -> Optional[str]:
    """Localiza o campo-base de um campo derivado (ex.: Resumo <- Descrição)."""
    nome = normalize(campo)
    for derivado, bases in CAMPOS_DERIVADOS.items():
        if nome != normalize(derivado):
            continue
        for base in bases:
            for chave in dados:
                if normalize(chave) == normalize(base):
                    return chave
    return None


def _achatar(valor: Any) -> str:
    """Converte valores compostos (listas/objetos) em texto verificável."""
    if valor is None:
        return ""
    if isinstance(valor, (list, tuple)):
        return "; ".join(_achatar(v) for v in valor if v is not None)
    if isinstance(valor, dict):
        return "; ".join(f"{k}: {_achatar(v)}" for k, v in valor.items())
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    return str(valor)


# ---------------------------------------------------------------------------
# Decomposição
# ---------------------------------------------------------------------------

def decompor(registros: Sequence[Dict[str, Any]]) -> List[Registro]:
    """Converte a lista de registros extraídos em afirmações atômicas."""
    saida: List[Registro] = []
    for indice, dados in enumerate(registros):
        if not isinstance(dados, dict):
            dados = {"valor": dados}
        registro = Registro(indice=indice, dados=dados)
        for campo, bruto in dados.items():
            valor = _achatar(bruto).strip()
            abstencao = is_abstention(valor)
            erro = is_extraction_error(valor)
            tipo = "texto" if (abstencao or erro) else inferir_tipo(campo, valor)
            base = _campo_base(campo, dados)
            valor_base = _achatar(dados.get(base)).strip() if base else None
            if valor_base and is_abstention(valor_base):
                valor_base = None
            registro.afirmacoes.append(Afirmacao(
                registro=indice,
                campo=campo,
                valor=valor,
                tipo=tipo,
                rotulos=_rotulos(campo, tipo),
                base_derivacao=base,
                valor_base=valor_base,
                abstencao=abstencao,
                erro_extracao=erro,
            ))
        saida.append(registro)
    return saida


# ---------------------------------------------------------------------------
# Carregamento da saída do extraction_tool
# ---------------------------------------------------------------------------

def carregar_registros(caminho: str | Path) -> List[Dict[str, Any]]:
    """
    Lê a saída do extraction_tool.

    Aceita `{task_id}_data.json` (lista de objetos), a resposta completa do
    endpoint `/api/status/<task_id>` (chave `extracted_data`) e o
    `{task_id}_data.csv`.
    """
    caminho = Path(caminho)
    texto = caminho.read_text(encoding="utf-8-sig")

    if caminho.suffix.lower() == ".csv":
        linhas = list(csv.DictReader(texto.splitlines()))
        return [dict(linha) for linha in linhas]

    dados = json.loads(texto)
    if isinstance(dados, dict):
        for chave in ("extracted_data", "dados_extraidos", "data", "resultados", "results"):
            if isinstance(dados.get(chave), list):
                return dados[chave]
        return [dados]
    if isinstance(dados, list):
        return dados
    raise ValueError(f"Formato não reconhecido em {caminho}")
