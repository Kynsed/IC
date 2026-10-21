"""Vínculo conservador entre entidade, atributo e evidência na fonte.

Presença lexical é uma etapa intermediária. Uma identidade explícita (nome,
título ou identificador) delimita a entidade; rótulos e marcação delimitam o
atributo. Ausência de informação suficiente resulta em PARCIAL, nunca em uma
associação inferida pela maioria dos valores gerados pelo modelo.
"""
from __future__ import annotations

import re
from typing import Optional

from .config import Veredito
from .normalizacao import normalize
from .restricoes import Coesao

_IDENTIDADES = {"nome", "name", "nome completo", "full name", "titulo", "title",
                "produto", "product", "id", "identificador", "identifier"}
_ROTULOS = re.compile(r"\b([^\W\d_]+(?:[ \t]+[^\W\d_]+){0,5})\s*:", re.UNICODE)
_FORTES = {"LEX-EXATO", "LEX-TOLERANTE", "TXT-EXATO", "NUM-ANCORADO", "NUM-MOEDA",
           "NUM-SEM-ROTULO", "NUM-LITERAL", "ID-ANCORADO", "DATA-LITERAL",
           "DATA-EQUIVALENTE", "URL-ANCORADA", "EMAIL-ANCORADO"}
_SINONIMOS = {
    "nome": {"nome", "name"}, "name": {"nome", "name"},
    "titulo": {"titulo", "title"}, "title": {"titulo", "title"},
    "idade": {"idade", "age"}, "age": {"idade", "age"},
    "preco": {"preco", "price"}, "price": {"preco", "price"},
    "autor": {"autor", "author"}, "author": {"autor", "author"},
    "editora": {"editora", "publisher"}, "publisher": {"editora", "publisher"},
    "paginas": {"paginas", "pages", "numero de paginas", "number of pages"},
    "numero de paginas": {"paginas", "pages", "numero de paginas", "number of pages"},
    "descricao": {"descricao", "description", "sinopse"},
}


def _nome(resultado):
    a = resultado.afirmacao
    return normalize(getattr(a, "campo_original", None) or a.campo).replace("_", " ")


def _aliases(resultado):
    nome = _nome(resultado)
    return (_SINONIMOS.get(nome, {nome}) |
            {normalize(r).replace("_", " ")
             for r in getattr(resultado.afirmacao, "rotulos_fonte", ())})


def _label_matches(label, resultado):
    return normalize(label).strip(" :.-").replace("_", " ") in _aliases(resultado)


def _identidade(resultado):
    return bool(getattr(resultado.afirmacao, "identidade", False) or
                _nome(resultado) in _IDENTIDADES)


def _ancestrais(base, no):
    return [no, *base.index.ancestors(no)] if no is not None else []


def _metadado(base, no):
    return any(base.index.nodes[n].tag in {"head", "script", "style", "template"}
               for n in _ancestrais(base, no))


def _entidade_dom(base, evidencia):
    no = base.node_of_evidence(evidencia)
    if no is None or _metadado(base, no):
        return None
    cadeia = _ancestrais(base, no)
    # article/tr delimitam entidades melhor que a lista de atributos dentro delas.
    for tags in ({"article", "tr"}, {"li", "dl", "section"}, {"div", "main"}):
        for n in cadeia:
            node = base.index.nodes[n]
            if node.tag in tags and len(base.index.chunks_in_subtree(n)) >= 2:
                return n
    # Uma página com um único título principal pode representar uma entidade.
    headings = [n for n in base.index.nodes if n.tag == "h1"]
    if len(headings) == 1 and headings[0].index in cadeia:
        return next((n for n in cadeia if base.index.nodes[n].tag == "body"), None)
    # Mesmo um item contendo só a identidade estabelece uma entidade vazia:
    # não autoriza buscar seus campos em outro article/tr.
    return next((n for n in cadeia if base.index.nodes[n].tag in {"article", "tr", "li"}), None)


def _dentro_dom(base, evidencia, ancora):
    no = base.node_of_evidence(evidencia)
    if no is None or ancora not in _ancestrais(base, no):
        return False
    # Todos os chunks do casamento devem pertencer à entidade, não apenas o primeiro.
    last = base.chunk_at(max(evidencia.flow_start, evidencia.flow_end - 1))
    return last is not None and ancora in _ancestrais(base, last.node)


def _escopo_texto(base, identidade, evidencia):
    inicio = evidencia.chunk_id
    if inicio is None:
        return frozenset()
    chunks = base.chunks
    ids = {inicio}
    linha = chunks[inicio].text
    # Só avançar para linhas seguintes quando há um registro explicitamente rotulado.
    labels = list(_ROTULOS.finditer(normalize(linha)))
    if any(_label_matches(m.group(1), identidade) for m in labels):
        for chunk in chunks[inicio + 1:]:
            if chunk.order > chunks[max(ids)].order + 1:
                break
            novos = list(_ROTULOS.finditer(normalize(chunk.text)))
            if any(_label_matches(m.group(1), identidade) for m in novos) or not novos:
                break
            ids.add(chunk.cid)
    else:
        # Linhas sem rótulo podem ser apenas quebras de diagramação. Uma
        # linha com o título não prova que o valor na linha seguinte é de
        # outra entidade; nesse caso a associação permanece inconclusiva.
        return frozenset()
    return frozenset(ids)


def _regiao_campo(base, evidencia, ancora):
    chunk = base.chunks[evidencia.chunk_id]
    if not base.index.structural:
        return [chunk]
    for n in _ancestrais(base, chunk.node):
        if n == ancora:
            break
        if base.index.nodes[n].tag in {"p", "li", "td", "th", "dd", "dt", "div"}:
            return base.index.chunks_in_subtree(n)
    return [chunk]


def vinculo_campo(resultado, evidencia, base, ancora=None) -> Optional[bool]:
    """True: atributo demonstrado; False: outro atributo; None: sem prova."""
    if evidencia.chunk_id is None:
        return None
    chunk = base.chunks[evidencia.chunk_id]
    no = chunk.node
    if base.index.structural and no is not None:
        for n in _ancestrais(base, no):
            if n == ancora:
                break
            node = base.index.nodes[n]
            for attr in ("itemprop", "name", "aria-label", "data-label", "class", "id"):
                value = node.attrs.get(attr, "")
                if _label_matches(value, resultado) or any(_label_matches(v, resultado) for v in value.split()):
                    return True
        node = base.index.nodes[no]
        # <dt>rótulo</dt><dd>valor</dd> e <th>rótulo</th><td>valor</td>.
        campo_no = next((n for n in _ancestrais(base, no)
                         if base.index.nodes[n].tag in {"dd", "td"}), None)
        if campo_no is not None:
            campo = base.index.nodes[campo_no]
            parent = base.index.nodes[campo.parent]
            siblings = parent.children
            pos = siblings.index(campo_no)
            if pos and base.index.nodes[siblings[pos - 1]].tag in {"dt", "th"}:
                label = base.index.text_of_subtree(siblings[pos - 1])
                return _label_matches(label, resultado)
            # Cabeçalho de tabela compartilha a coluna, não a janela de texto.
            if campo.tag == "td" and parent.tag == "tr":
                tabela = next((n for n in _ancestrais(base, parent.index)
                               if base.index.nodes[n].tag == "table"), None)
                coluna = [n for n in siblings if base.index.nodes[n].tag in {"td", "th"}].index(campo_no)
                if tabela is not None:
                    headers = [n for n in base.index.subtree(tabela) if base.index.nodes[n].tag == "tr"
                               and any(base.index.nodes[c].tag == "th" for c in base.index.nodes[n].children)]
                    if headers:
                        cells = [n for n in base.index.nodes[headers[0]].children
                                 if base.index.nodes[n].tag in {"td", "th"}]
                        if coluna < len(cells):
                            return _label_matches(base.index.text_of_subtree(cells[coluna]), resultado)
    region = _regiao_campo(base, evidencia, ancora)
    text = " ".join(c.text for c in region)
    # Localizar o match na região mantendo offsets de cada chunk já normalizado.
    local = sum(len(c.text) + 1 for c in region if c.cid < chunk.cid)
    local += evidencia.flow_start - base._chunk_starts[chunk.cid]
    labels = [m for m in _ROTULOS.finditer(normalize(text)) if m.end() <= local]
    if labels:
        return _label_matches(labels[-1].group(1), resultado)
    # Rótulo em chunk separado: não usar o vizinho de outra entidade.
    if chunk.cid:
        anterior = base.chunks[chunk.cid - 1]
        mesmo_pai = (base.index.structural and no is not None and anterior.node is not None
                     and base.index.nodes[no].parent == base.index.nodes[anterior.node].parent)
        if mesmo_pai and _label_matches(anterior.text, resultado):
            return True
    # Uma unidade explícita pode definir um atributo específico.
    after = normalize(text)[local + len(evidencia.snippet_match):]
    if _nome(resultado) in {"idade", "age"} and re.match(r"\s*(?:anos|years old)\b", after):
        return True
    # 'Preço' genérico é demonstrado pelo símbolo monetário; subtipos (atual,
    # antigo, frete) continuam exigindo seus próprios rótulos.
    if _nome(resultado) in {"preco", "price"} and evidencia.unit is not None:
        return True
    return None


def _parcial(resultado, nota):
    if resultado.veredito == Veredito.SUPORTADA:
        resultado.veredito = Veredito.PARCIAL
        resultado.regra = "CTX-INCONCLUSIVO"
        resultado.notas.append(nota)


def verificar_contexto(resultados, base, config) -> Coesao:
    """Classifica associações e devolve a única entidade explicitamente ancorada."""
    ativos = [r for r in resultados if r.veredito in {Veredito.SUPORTADA, Veredito.PARCIAL}
              and not r.afirmacao.derivada]
    declaradas = [r for r in resultados if _identidade(r) and not r.afirmacao.derivada]
    identidades = [r for r in ativos if _identidade(r) and r.regra in _FORTES]
    estrutural = base.index.structural
    scopes = None
    for identidade in identidades:
        locais = set()
        for e in identidade.evidencias:
            if e.negacao_externa:
                continue
            scope = _entidade_dom(base, e) if estrutural else _escopo_texto(base, identidade, e)
            if scope is not None and scope != frozenset():
                locais.add(scope)
        scopes = locais if scopes is None else scopes & locais
    if declaradas and (len(identidades) != len(declaradas) or not scopes or len(scopes) != 1):
        for r in ativos:
            if r not in identidades:
                _parcial(r, "a identidade não delimita uma única entidade na fonte")
        return Coesao(0.0, None, "", [], [], False)
    scope = next(iter(scopes)) if scopes else None
    ancora = scope if estrutural else None
    dentro, fora = [], []
    for r in ativos:
        if r.regra not in _FORTES:
            continue  # similaridade/cobertura nunca é promovida a prova relacional
        if scope is None:
            locais = r.evidencias
        elif estrutural:
            locais = [e for e in r.evidencias if _dentro_dom(base, e, scope)]
        else:
            locais = [e for e in r.evidencias if e.chunk_id in scope and
                      base.chunk_at(max(e.flow_start, e.flow_end - 1)).cid in scope]
        if scope is not None and not locais:
            r.veredito = Veredito.ATRIBUICAO_INCORRETA
            r.regra = "DOM-FORA-DA-ANCORA" if estrutural else "CTX-OUTRA-ENTIDADE"
            r.notas.append("o valor existe, mas fora da entidade identificada pelo nome/título")
            fora.append(r.afirmacao.campo)
            continue
        if locais and r.evidencias[0] is not locais[0]:
            r.evidencias.remove(locais[0]); r.evidencias.insert(0, locais[0])
        if r in identidades:
            dentro.append(r.afirmacao.campo)
            continue
        bindings = [(e, vinculo_campo(r, e, base, ancora)) for e in locais]
        confirmadas = [e for e, state in bindings if state is True and not e.negacao_externa]
        if confirmadas:
            chosen = confirmadas[0]
            if r.evidencias[0] is not chosen:
                r.evidencias.remove(chosen); r.evidencias.insert(0, chosen)
            # NUM-SEM-ROTULO é uma magnitude exata que ganhou um rótulo contextual.
            r.veredito = Veredito.SUPORTADA
            dentro.append(r.afirmacao.campo)
        elif bindings and all(state is False for _, state in bindings):
            r.veredito = Veredito.ATRIBUICAO_INCORRETA
            r.regra = "CTX-OUTRO-ATRIBUTO"
            r.notas.append("as ocorrências encontradas estão explicitamente vinculadas a outro atributo")
            fora.append(r.afirmacao.campo)
        elif bindings and all(e.negacao_externa for e, _ in bindings):
            _parcial(r, "as ocorrências locais estão sob negação externa")
        elif r.afirmacao.tipo in {"texto", "texto_longo"} and r.regra == "TXT-EXATO":
            dentro.append(r.afirmacao.campo)  # transcrição da descrição no item identificado
        else:
            _parcial(r, "presença do valor confirmada, mas o vínculo com o atributo não foi demonstrado")
            if scope is not None:
                dentro.append(r.afirmacao.campo)
    caminho = base.index.nodes[ancora].path if ancora is not None else (
        ", ".join(base.chunks[c].path for c in sorted(scope)) if scope is not None else "")
    total = len(dentro) + len(fora)
    return Coesao(len(dentro) / total if total else 0.0, ancora, caminho,
                  dentro, fora, scope is not None,
                  list(sorted(scope)) if scope is not None and not estrutural else [])
