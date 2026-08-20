"""
Indexação simbólica da fonte (HTML bruto ou texto limpo).

Este módulo constrói a **base de fatos** contra a qual as afirmações do LLM
serão confrontadas. O parsing do HTML usa exclusivamente `html.parser` da
biblioteca padrão do Python -- não há dependência de BeautifulSoup em nenhum
ponto do pipeline de verificação.

Duas fontes são suportadas:

* `parse_html(...)`  -> índice estrutural completo (árvore DOM, caminhos CSS,
  atributos, ancestralidade). Permite as regras de localidade no DOM.
* `parse_text(...)`  -> índice linear por linhas, usado quando só se dispõe do
  arquivo `{task_id}_text.txt` produzido pelo extraction_tool. A verificação
  lexical continua válida; apenas as regras estruturais são puladas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Dict, Iterable, List, Optional, Sequence

from .normalizacao import clean_whitespace, looks_like_html

__all__ = ["Node", "Chunk", "SourceIndex", "parse_html", "parse_text", "parse_source"]

# Elementos sem conteúdo (não empilham).
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}

# Fechamento implícito: abrir a chave fecha os elementos abertos do conjunto.
IMPLIED_CLOSE: Dict[str, set] = {
    "li": {"li"},
    "dt": {"dt", "dd"},
    "dd": {"dt", "dd"},
    "tr": {"tr", "td", "th"},
    "td": {"td", "th"},
    "th": {"td", "th"},
    "option": {"option"},
    "thead": {"thead", "tbody"},
    "tbody": {"thead", "tbody"},
    "tfoot": {"thead", "tbody", "tfoot"},
    "p": {"p"},
}
_BLOCK_CLOSES_P = {
    "div", "section", "article", "aside", "header", "footer", "main", "nav",
    "ul", "ol", "dl", "table", "form", "figure", "blockquote", "pre", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6", "address",
}

# Elementos cujo conteúdo textual não é conteúdo da página.
NON_CONTENT_TAGS = {"script", "style", "template", "svg", "head"}

# Atributos que carregam conteúdo factual verificável (preço em microdata,
# texto alternativo de imagem, datas em <time>, destinos de links...).
CONTENT_ATTRS = ("content", "alt", "title", "value", "aria-label",
                 "placeholder", "datetime", "href", "src")


@dataclass
class Node:
    """Elemento da árvore DOM."""
    index: int
    tag: str
    attrs: Dict[str, str]
    parent: Optional[int]
    depth: int
    order: int                       # ordem de abertura no documento
    children: List[int] = field(default_factory=list)
    start: int = 0                   # offset no HTML bruto
    end: int = 0
    path: str = ""                   # caminho tipo CSS, para rastreabilidade

    @property
    def identifier(self) -> str:
        ident = self.tag
        if self.attrs.get("id"):
            ident += "#" + self.attrs["id"]
        classes = (self.attrs.get("class") or "").split()
        if classes:
            ident += "." + ".".join(classes[:2])
        return ident


@dataclass
class Chunk:
    """
    Unidade mínima de evidência: um nó de texto ou o valor de um atributo.

    Cada afirmação verificada aponta para um ou mais chunks, e cada chunk
    aponta para sua posição exata na fonte -- é isso que torna o veredito
    auditável.
    """
    cid: int
    text: str                        # texto original (apenas espaços colapsados)
    kind: str                        # 'text' | 'attr:<nome>' | 'line'
    node: Optional[int]
    path: str
    start: int                       # offset na fonte bruta
    order: int                       # ordem de leitura (linha, no modo texto)


class SourceIndex:
    """Índice da fonte: nós (quando HTML) + sequência linear de chunks."""

    def __init__(self, kind: str, raw: str, nodes: List[Node], chunks: List[Chunk]):
        self.kind = kind                  # 'html' | 'text'
        self.raw = raw
        self.nodes = nodes
        self.chunks = chunks
        self._by_node: Dict[int, List[int]] = {}
        for chunk in chunks:
            if chunk.node is not None:
                self._by_node.setdefault(chunk.node, []).append(chunk.cid)

    # -- consultas estruturais ------------------------------------------------

    @property
    def structural(self) -> bool:
        """True quando há árvore DOM (regras de localidade aplicáveis)."""
        return self.kind == "html" and bool(self.nodes)

    def ancestors(self, node_index: int) -> List[int]:
        """Cadeia de ancestrais, do pai imediato até a raiz."""
        out: List[int] = []
        current = self.nodes[node_index].parent if self.nodes else None
        while current is not None:
            out.append(current)
            current = self.nodes[current].parent
        return out

    def subtree(self, node_index: int) -> List[int]:
        """Índices de todos os nós da subárvore (inclui a raiz informada)."""
        out: List[int] = []
        stack = [node_index]
        while stack:
            current = stack.pop()
            out.append(current)
            stack.extend(self.nodes[current].children)
        return out

    def chunks_of_node(self, node_index: int) -> List[Chunk]:
        return [self.chunks[c] for c in self._by_node.get(node_index, ())]

    def chunks_in_subtree(self, node_index: int) -> List[Chunk]:
        out: List[Chunk] = []
        for idx in self.subtree(node_index):
            out.extend(self.chunks_of_node(idx))
        out.sort(key=lambda c: c.order)
        return out

    def text_of_subtree(self, node_index: int, limit: int = 4000) -> str:
        parts = [c.text for c in self.chunks_in_subtree(node_index) if c.kind == "text"]
        return clean_whitespace(" ".join(parts))[:limit]

    def describe(self) -> str:
        if self.structural:
            return (f"DOM: {len(self.nodes)} elementos, "
                    f"{len(self.chunks)} unidades de evidência")
        return f"texto: {len(self.chunks)} linhas de evidência"


# ---------------------------------------------------------------------------
# Parser HTML (stdlib)
# ---------------------------------------------------------------------------

class _DomBuilder(HTMLParser):
    """Constrói a árvore tolerando marcação malformada (tags não fechadas)."""

    def __init__(self, raw: str):
        super().__init__(convert_charrefs=True)
        self.raw = raw
        self._line_starts = self._compute_line_starts(raw)
        self.nodes: List[Node] = []
        self.chunks: List[Chunk] = []
        self._stack: List[int] = []
        self._order = 0

        root = Node(index=0, tag="#document", attrs={}, parent=None, depth=0, order=0)
        self.nodes.append(root)
        self._stack.append(0)

    # -- utilidades -----------------------------------------------------------

    @staticmethod
    def _compute_line_starts(raw: str) -> List[int]:
        starts, pos = [0], raw.find("\n")
        while pos != -1:
            starts.append(pos + 1)
            pos = raw.find("\n", pos + 1)
        return starts

    def _offset(self) -> int:
        line, col = self.getpos()
        if 1 <= line <= len(self._line_starts):
            return self._line_starts[line - 1] + col
        return 0

    @property
    def _current(self) -> int:
        return self._stack[-1]

    def _in_non_content(self) -> bool:
        return any(self.nodes[i].tag in NON_CONTENT_TAGS for i in self._stack)

    def _add_chunk(self, text: str, kind: str, node: int, start: int) -> None:
        cleaned = clean_whitespace(text)
        if not cleaned:
            return
        self.chunks.append(Chunk(
            cid=len(self.chunks), text=cleaned, kind=kind, node=node,
            path=self.nodes[node].path, start=start, order=len(self.chunks),
        ))

    # -- callbacks ------------------------------------------------------------

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        # fechamentos implícitos
        while len(self._stack) > 1:
            top = self.nodes[self._current].tag
            closes = IMPLIED_CLOSE.get(top, set())
            if tag in closes or (top == "p" and tag in _BLOCK_CLOSES_P):
                self._close(self._current)
            else:
                break

        parent = self._current
        self._order += 1
        node = Node(
            index=len(self.nodes), tag=tag,
            attrs={k.lower(): (v or "") for k, v in attrs},
            parent=parent, depth=self.nodes[parent].depth + 1,
            order=self._order, start=self._offset(),
        )
        self.nodes.append(node)
        self.nodes[parent].children.append(node.index)
        node.path = self._build_path(node)

        for name in CONTENT_ATTRS:
            value = node.attrs.get(name)
            if value and len(value) < 2000:
                self._add_chunk(value, f"attr:{name}", node.index, node.start)

        if tag not in VOID_TAGS:
            self._stack.append(node.index)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS and self._current != 0:
            self._close(self._current)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in VOID_TAGS:
            return
        for pos in range(len(self._stack) - 1, 0, -1):
            if self.nodes[self._stack[pos]].tag == tag:
                while len(self._stack) > pos:
                    self._close(self._current)
                return
        # tag de fechamento órfã: ignorada (tolerância a marcação inválida)

    def handle_data(self, data):
        if not data.strip() or self._in_non_content():
            return
        self._add_chunk(data, "text", self._current, self._offset())

    def _close(self, node_index: int) -> None:
        self.nodes[node_index].end = self._offset()
        if len(self._stack) > 1:
            self._stack.pop()

    def _build_path(self, node: Node) -> str:
        parent = self.nodes[node.parent] if node.parent is not None else None
        if parent is None:
            return node.tag
        same_tag = [i for i in parent.children if self.nodes[i].tag == node.tag]
        nth = len(same_tag)  # o próprio nó já foi anexado
        segment = node.identifier + (f":nth-of-type({nth})" if nth > 1 else "")
        prefix = parent.path
        return f"{prefix} > {segment}" if prefix and prefix != "#document" else segment

    def finish(self) -> None:
        end = len(self.raw)
        for node in self.nodes:
            if node.end == 0:
                node.end = end


def parse_html(raw: str) -> SourceIndex:
    """Constrói o índice estrutural a partir do HTML bruto (sem BeautifulSoup)."""
    builder = _DomBuilder(raw)
    builder.feed(raw)
    builder.close()
    builder.finish()
    return SourceIndex("html", raw, builder.nodes, builder.chunks)


def parse_text(raw: str) -> SourceIndex:
    """Índice linear para o texto já limpo (`{task_id}_text.txt`)."""
    chunks: List[Chunk] = []
    offset = 0
    for line_no, line in enumerate(raw.splitlines(keepends=True)):
        cleaned = clean_whitespace(line)
        if cleaned:
            chunks.append(Chunk(
                cid=len(chunks), text=cleaned, kind="line", node=None,
                path=f"linha[{line_no + 1}]", start=offset, order=line_no,
            ))
        offset += len(line)
    return SourceIndex("text", raw, [], chunks)


def parse_source(raw: str, force: Optional[str] = None) -> SourceIndex:
    """
    Escolhe o parser adequado.

    `force` aceita 'html' ou 'text'; por padrão a natureza da fonte é
    detectada pelo conteúdo.
    """
    if force == "html" or (force is None and looks_like_html(raw)):
        return parse_html(raw)
    return parse_text(raw)
