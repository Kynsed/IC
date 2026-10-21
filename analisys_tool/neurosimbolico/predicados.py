"""
Predicados simbólicos de verificação factual.

Cada afirmação atômica passa por uma cadeia de predicados determinísticos,
ordenados do mais forte (casamento literal na fonte) ao mais fraco
(similaridade aproximada). A cadeia para no primeiro predicado que produz
suporte pleno; caso contrário, o melhor resultado parcial é reportado.

Todo veredito carrega (i) a regra que o produziu e (ii) a citação exata na
fonte -- os dois requisitos de rastreabilidade da verificação neuro-simbólica.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .afirmacoes import Afirmacao
from .config import Config, Veredito
from .evidencias import Evidence, EvidenceBase
from .normalizacao import (
    content_tokens,
    currency_code,
    date_renderings,
    decimal_variants,
    ean_valid,
    isbn_valid,
    iter_numbers,
    normalize,
    parse_date,
    tokenize,
    word_count,
)

__all__ = ["ResultadoAfirmacao", "verificar_afirmacao"]

_URL_RE = re.compile(r"^(https?://)?([\w-]+\.)+[a-z]{2,}(/\S*)?$", re.I)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
_MAIUSCULA_RE = re.compile(r"\b([A-ZÀ-Ý][\wÀ-ÿ'-]{2,})")


@dataclass
class ResultadoAfirmacao:
    """Veredito rastreável de uma afirmação atômica."""
    afirmacao: Afirmacao
    veredito: str
    score: float
    regra: str
    evidencias: List[Evidence] = field(default_factory=list)
    notas: List[str] = field(default_factory=list)
    tokens_novos: List[str] = field(default_factory=list)
    numeros_novos: List[str] = field(default_factory=list)

    @property
    def evidencia_principal(self) -> Optional[Evidence]:
        return self.evidencias[0] if self.evidencias else None

    @property
    def alucinacao(self) -> bool:
        """Erro factual: valor inexistente, mal formado ou atribuído ao item errado."""
        return self.veredito in Veredito.REPROVADOS

    def to_dict(self) -> dict:
        return {
            "registro": self.afirmacao.registro,
            "campo": self.afirmacao.campo,
            "campo_original": self.afirmacao.campo_original or self.afirmacao.campo,
            "caminho": list(self.afirmacao.caminho),
            "valor": self.afirmacao.valor,
            "valor_bruto": self.afirmacao.valor_bruto,
            "tipo": self.afirmacao.tipo,
            "veredito": self.veredito,
            "score": round(self.score, 4),
            "regra": self.regra,
            "notas": self.notas,
            "tokens_novos": self.tokens_novos[:20],
            "numeros_novos": self.numeros_novos[:20],
            "evidencias": [e.to_dict() for e in self.evidencias[:3]],
            "total_evidencias": len(self.evidencias),
        }


def _res(afirmacao, veredito, score, regra, evidencias=None, notas=None,
         tokens_novos=None, numeros_novos=None) -> ResultadoAfirmacao:
    return ResultadoAfirmacao(
        afirmacao=afirmacao, veredito=veredito, score=score, regra=regra,
        evidencias=list(evidencias or []), notas=list(notas or []),
        tokens_novos=list(tokens_novos or []), numeros_novos=list(numeros_novos or []),
    )


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def verificar_afirmacao(afirmacao: Afirmacao, base: EvidenceBase,
                        config: Config) -> ResultadoAfirmacao:
    """Aplica a cadeia de predicados adequada ao tipo da afirmação."""
    if afirmacao.erro_extracao:
        return _res(afirmacao, Veredito.ERRO_EXTRACAO, 0.0, "PRE-ERRO",
                    notas=["marcador de falha emitido pelo extraction_tool"])
    if afirmacao.abstencao:
        return _res(afirmacao, Veredito.ABSTENCAO, 0.0, "PRE-ABSTENCAO",
                    notas=["o modelo declarou ausência do dado (não é alucinação)"])
    if not afirmacao.valor.strip():
        return _res(afirmacao, Veredito.ABSTENCAO, 0.0, "PRE-VAZIO")

    if afirmacao.derivada:
        return _verificar_derivada(afirmacao, base, config)

    despacho = {
        "moeda": _verificar_numerico,
        "numero": _verificar_numerico,
        "inteiro": _verificar_numerico,
        "ano": _verificar_numerico,
        "avaliacao": _verificar_numerico,
        "isbn": _verificar_identificador,
        "ean": _verificar_identificador,
        "url": _verificar_url,
        "email": _verificar_email,
        "data": _verificar_data,
        "texto_longo": _verificar_texto_longo,
    }
    resultado = despacho.get(afirmacao.tipo, _verificar_texto_curto)(afirmacao, base, config)
    if (resultado.veredito == Veredito.SUPORTADA and resultado.evidencias and
            all(e.negacao_externa for e in resultado.evidencias)):
        resultado.veredito = Veredito.PARCIAL
        resultado.notas.append("o trecho ocorre sob negação externa; presença lexical não comprova o fato")
    return resultado


# ---------------------------------------------------------------------------
# Texto curto
# ---------------------------------------------------------------------------

def _verificar_texto_curto(afirmacao: Afirmacao, base: EvidenceBase,
                           config: Config) -> ResultadoAfirmacao:
    valor = afirmacao.valor

    exatas = base.find_literal(valor)
    if exatas:
        return _res(afirmacao, Veredito.SUPORTADA, 1.0, "LEX-EXATO", exatas)

    tolerantes = base.find_loose(valor)
    if tolerantes:
        return _res(afirmacao, Veredito.SUPORTADA, 0.95, "LEX-TOLERANTE", tolerantes,
                    notas=["casamento com variação de pontuação/espaçamento"])

    fuzzy_score, fuzzy_ev = base.best_fuzzy(valor)
    if fuzzy_score >= config.fuzzy_suporte and fuzzy_ev:
        return _res(afirmacao, Veredito.PARCIAL, fuzzy_score, "LEX-APROXIMADO", [fuzzy_ev],
                    notas=[f"similaridade {fuzzy_score:.2f}; similaridade não comprova equivalência factual"])

    janela, janela_ev = base.best_window(valor)
    cobertura, faltantes = base.coverage(valor)
    numeros_novos = base.novel_numbers(valor)

    if janela >= 0.999 and janela_ev and len(content_tokens(valor)) >= 2:
        return _res(afirmacao, Veredito.PARCIAL, 0.80, "LEX-JANELA", [janela_ev],
                    notas=["todos os tokens ocorrem na mesma região, "
                           "mas não na forma exata afirmada"])

    if fuzzy_score >= config.fuzzy_parcial and fuzzy_ev:
        return _res(afirmacao, Veredito.PARCIAL, fuzzy_score, "LEX-APROXIMADO", [fuzzy_ev],
                    notas=[f"similaridade {fuzzy_score:.2f} (abaixo do limiar de suporte)"],
                    tokens_novos=faltantes, numeros_novos=numeros_novos)

    if cobertura >= config.cobertura_parcial and janela_ev:
        return _res(afirmacao, Veredito.PARCIAL, cobertura, "LEX-COBERTURA", [janela_ev],
                    notas=[f"cobertura lexical de {cobertura:.0%}; "
                           f"tokens ausentes na fonte: {', '.join(faltantes[:6]) or '—'}"],
                    tokens_novos=faltantes, numeros_novos=numeros_novos)

    evidencias = [fuzzy_ev] if fuzzy_ev else []
    return _res(afirmacao, Veredito.NAO_SUPORTADA, 1.0 - cobertura, "LEX-SEM-ANCORA", evidencias,
                notas=["valor não localizado na fonte"],
                tokens_novos=faltantes, numeros_novos=numeros_novos)


# ---------------------------------------------------------------------------
# Numéricos (preço, quantidade, ano, avaliação)
# ---------------------------------------------------------------------------

def _verificar_numerico(afirmacao: Afirmacao, base: EvidenceBase,
                        config: Config) -> ResultadoAfirmacao:
    valor = afirmacao.valor
    valores = decimal_variants(valor)
    if not valores:
        return _res(afirmacao, Veredito.INVALIDA, 0.0, "NUM-FORMATO",
                    notas=["esperado um único literal numérico, sem concatenar números ou texto"])

    principal = max(valores, key=abs)

    # -- restrições de domínio (independem da fonte) ----------------------
    if afirmacao.tipo == "ano":
        ano = int(principal)
        limite = date.fromisoformat(config.data_referencia).year + config.ano_maximo_folga
        if not (config.ano_minimo <= ano <= limite):
            return _res(afirmacao, Veredito.INVALIDA, 1.0, "SIM-ANO-INTERVALO",
                        notas=[f"ano {ano} fora do intervalo plausível "
                               f"[{config.ano_minimo}, {limite}]"])
    if afirmacao.tipo in ("inteiro", "moeda") and principal < 0:
        return _res(afirmacao, Veredito.INVALIDA, 1.0, "SIM-NEGATIVO",
                    notas=[f"valor negativo inválido para o campo '{afirmacao.campo}'"])
    if afirmacao.tipo == "inteiro" and principal != principal.to_integral_value():
        return _res(afirmacao, Veredito.INVALIDA, 1.0, "SIM-NAO-INTEIRO",
                    notas=[f"esperado inteiro, obtido {principal}"])

    # -- ancoragem numérica (equivalência de valor) ------------------------
    candidatas = base.find_numeric(valores)
    unidade = currency_code(valor)
    if unidade and candidatas:
        compativeis = [e for e in candidatas if e.unit == unidade]
        incertas = [e for e in candidatas if e.unit is None]
        if compativeis:
            candidatas = compativeis
        elif incertas:
            return _res(afirmacao, Veredito.PARCIAL, 0.5, "NUM-UNIDADE-INCERTA", incertas,
                        notas=[f"magnitude presente, mas a unidade {unidade} não está comprovada"])
        else:
            return _res(afirmacao, Veredito.NAO_SUPORTADA, 0.0, "NUM-UNIDADE-DIVERGENTE", candidatas,
                        notas=[f"mesma magnitude, porém moeda diferente de {unidade}"])
    if candidatas:
        rotuladas: List[Tuple[Evidence, str]] = []
        for evidencia in candidatas:
            rotulo = base.label_near(evidencia.flow_start, evidencia.flow_end,
                                     afirmacao.rotulos, config.janela_rotulo)
            if rotulo:
                rotuladas.append((evidencia, rotulo))
        if rotuladas:
            rotulo = rotuladas[0][1]
            evidencias = []
            # A proximidade escolhe a apresentação inicial, mas não pode
            # descartar ocorrências que a etapa contextual ainda avaliará.
            for evidencia in candidatas:
                evidencia.rule = "NUM-ANCORADO"
                evidencias.append(evidencia)
            return _res(afirmacao, Veredito.SUPORTADA, 1.0, "NUM-ANCORADO", evidencias,
                        notas=[f"valor numérico equivalente encontrado junto ao rótulo '{rotulo}'"])
        monetarias = [e for e in candidatas if "monetário" in e.detail]
        if afirmacao.tipo == "moeda" and monetarias:
            return _res(afirmacao, Veredito.SUPORTADA, 0.90, "NUM-MOEDA", monetarias,
                        notas=["valor equivalente com símbolo monetário na fonte"])
        return _res(afirmacao, Veredito.PARCIAL, config.score_numero_sem_rotulo,
                    "NUM-SEM-ROTULO", candidatas,
                    notas=["número presente na fonte, porém sem rótulo do campo "
                           "nas proximidades: a associação campo-valor não pôde ser confirmada"])

    return _res(afirmacao, Veredito.NAO_SUPORTADA, 1.0, "NUM-AUSENTE",
                notas=[f"o valor numérico {principal} não ocorre na fonte"],
                numeros_novos=[valor])


# ---------------------------------------------------------------------------
# Identificadores com dígito verificador (ISBN / EAN)
# ---------------------------------------------------------------------------

def _verificar_identificador(afirmacao: Afirmacao, base: EvidenceBase,
                             config: Config) -> ResultadoAfirmacao:
    valor = afirmacao.valor
    checagem = isbn_valid(valor) if afirmacao.tipo == "isbn" else ean_valid(valor)

    notas: List[str] = []
    if checagem is None:
        notas.append("forma não reconhecida: dígito verificador não aplicável")
    elif checagem:
        notas.append("dígito verificador válido")
    else:
        notas.append("dígito verificador INVÁLIDO")

    encontradas = base.find_literal(valor) or base.find_loose(valor)
    if not encontradas:
        digitos = re.sub(r"[^0-9xX]", "", valor)
        if len(digitos) >= 8:
            padrao = r"(?<!\w)" + r"[\W_]{0,3}".join(re.escape(d) for d in digitos) + r"(?!\w)"
            encontradas = base.find_regex(padrao, "ID-DIGITOS", 0.95)

    if encontradas:
        veredito = Veredito.SUPORTADA
        if checagem is False:
            notas.append("o identificador consta na fonte, mas seu dígito verificador "
                         "não fecha: possível erro da própria página")
        return _res(afirmacao, veredito, 1.0, "ID-ANCORADO", encontradas, notas)

    if checagem is False:
        notas.append("identificador ausente da fonte e formalmente inválido: "
                     "forte indício de fabricação")
        return _res(afirmacao, Veredito.INVALIDA, 1.0, "SIM-CHECKSUM", notas=notas)

    notas.append("identificador ausente da fonte")
    return _res(afirmacao, Veredito.NAO_SUPORTADA, 1.0, "ID-AUSENTE", notas=notas)


# ---------------------------------------------------------------------------
# URL e e-mail
# ---------------------------------------------------------------------------

def _verificar_url(afirmacao: Afirmacao, base: EvidenceBase,
                   config: Config) -> ResultadoAfirmacao:
    valor = afirmacao.valor.strip()
    if not _URL_RE.match(valor):
        return _res(afirmacao, Veredito.INVALIDA, 1.0, "SIM-URL-FORMATO",
                    notas=["URL sintaticamente inválida"])

    encontradas = base.find_literal(valor) or base.find_loose(valor)
    if encontradas:
        return _res(afirmacao, Veredito.SUPORTADA, 1.0, "URL-ANCORADA", encontradas)

    host = re.sub(r"^https?://", "", valor).split("/")[0]
    por_host = base.find_literal(host, rule="URL-HOST")
    if por_host:
        return _res(afirmacao, Veredito.PARCIAL, 0.7, "URL-HOST", por_host,
                    notas=[f"apenas o domínio '{host}' consta na fonte; "
                           "o caminho completo não foi confirmado"])
    return _res(afirmacao, Veredito.NAO_SUPORTADA, 1.0, "URL-AUSENTE",
                notas=["URL não referenciada na fonte"])


def _verificar_email(afirmacao: Afirmacao, base: EvidenceBase,
                     config: Config) -> ResultadoAfirmacao:
    valor = afirmacao.valor.strip()
    if not _EMAIL_RE.match(valor):
        return _res(afirmacao, Veredito.INVALIDA, 1.0, "SIM-EMAIL-FORMATO",
                    notas=["endereço de e-mail sintaticamente inválido"])
    encontradas = base.find_literal(valor) or base.find_loose(valor)
    if encontradas:
        return _res(afirmacao, Veredito.SUPORTADA, 1.0, "EMAIL-ANCORADO", encontradas)
    return _res(afirmacao, Veredito.NAO_SUPORTADA, 1.0, "EMAIL-AUSENTE",
                notas=["e-mail não encontrado na fonte"])


# ---------------------------------------------------------------------------
# Datas
# ---------------------------------------------------------------------------

def _verificar_data(afirmacao: Afirmacao, base: EvidenceBase,
                    config: Config) -> ResultadoAfirmacao:
    valor = afirmacao.valor
    data = parse_date(valor)
    if data is None:
        return _res(afirmacao, Veredito.INVALIDA, 1.0, "SIM-DATA-FORMATO",
                    notas=["data não interpretável"])

    encontradas = base.find_literal(valor) or base.find_loose(valor)
    if encontradas:
        return _res(afirmacao, Veredito.SUPORTADA, 1.0, "DATA-LITERAL", encontradas)

    for forma in date_renderings(data):
        equivalentes = base.find_loose(forma)
        if equivalentes:
            return _res(afirmacao, Veredito.SUPORTADA, 0.95, "DATA-EQUIVALENTE",
                        equivalentes,
                        notas=[f"mesma data em formato distinto na fonte ('{forma}')"])

    if base.numbers_present({Decimal(data.year)}):
        parciais = base.find_numeric({Decimal(data.year)}, rule="DATA-ANO")
        return _res(afirmacao, Veredito.PARCIAL, 0.5, "DATA-ANO", parciais,
                    notas=["apenas o ano foi confirmado na fonte; "
                           "dia e mês não puderam ser ancorados"])

    return _res(afirmacao, Veredito.NAO_SUPORTADA, 1.0, "DATA-AUSENTE",
                notas=["data não localizada na fonte"])


# ---------------------------------------------------------------------------
# Texto longo (descrição / sinopse)
# ---------------------------------------------------------------------------

def _verificar_texto_longo(afirmacao: Afirmacao, base: EvidenceBase,
                           config: Config) -> ResultadoAfirmacao:
    valor = afirmacao.valor

    exatas = base.find_literal(valor)
    if exatas:
        # Guardar várias ocorrências, e não apenas a primeira: um mesmo texto
        # costuma aparecer no <head>, no cabeçalho e no corpo do item, e é a
        # re-ancoragem (calcular_coesao) que escolhe entre elas a que pertence
        # à subárvore do registro. Com uma só, um casamento em <meta> faria o
        # campo parecer vindo de outro item da página.
        return _res(afirmacao, Veredito.SUPORTADA, 1.0, "TXT-EXATO", exatas,
                    notas=["transcrição literal do conteúdo da fonte"])

    janela, janela_ev = base.best_window(valor)
    cobertura, faltantes = base.coverage(valor)
    numeros_novos = base.novel_numbers(valor)
    evidencias = [janela_ev] if janela_ev else []

    notas = [f"cobertura local {janela:.0%} / global {cobertura:.0%}"]
    if faltantes:
        notas.append("tokens ausentes da fonte: " + ", ".join(faltantes[:10]))
    if numeros_novos:
        notas.append("números não presentes na fonte: " + ", ".join(numeros_novos[:8]))

    if janela >= config.cobertura_suporte and not numeros_novos:
        return _res(afirmacao, Veredito.PARCIAL, janela, "TXT-COBERTURA-ALTA",
                    evidencias, notas + ["cobertura lexical não comprova relações, ordem ou negação"],
                    faltantes, numeros_novos)
    if janela >= config.janela_suporte or cobertura >= config.cobertura_suporte:
        return _res(afirmacao, Veredito.PARCIAL, max(janela, cobertura),
                    "TXT-COBERTURA-PARCIAL", evidencias,
                    notas + ["conteúdo majoritariamente ancorado, com acréscimos "
                             "não suportados pela fonte"], faltantes, numeros_novos)
    if max(janela, cobertura) >= config.cobertura_parcial:
        return _res(afirmacao, Veredito.PARCIAL, max(janela, cobertura),
                    "TXT-COBERTURA-BAIXA", evidencias, notas, faltantes, numeros_novos)

    return _res(afirmacao, Veredito.NAO_SUPORTADA, 1.0 - max(janela, cobertura),
                "TXT-SEM-ANCORA", evidencias,
                notas + ["conteúdo majoritariamente não localizado na fonte"],
                faltantes, numeros_novos)


# ---------------------------------------------------------------------------
# Campos derivados (Resumo <- Descrição): verificação de vínculo (entailment)
# ---------------------------------------------------------------------------

def _entidades(texto: str) -> Set[str]:
    """Tokens iniciados por maiúscula que não abrem período (nomes próprios)."""
    saida: Set[str] = set()
    for sentenca in re.split(r"[.!?;]\s+", texto):
        palavras = sentenca.split()
        for palavra in palavras[1:]:
            achado = _MAIUSCULA_RE.match(palavra)
            if achado:
                saida.add(normalize(achado.group(1)))
    return saida


def _verificar_derivada(afirmacao: Afirmacao, base: EvidenceBase,
                        config: Config) -> ResultadoAfirmacao:
    """
    Um campo derivado (ex.: 'Resumo') não deve ser confrontado com a página,
    e sim com o campo que lhe deu origem: sua base factual é a 'Descrição'
    extraída, e é contra ela que se mede o acréscimo indevido de conteúdo.
    """
    valor, origem = afirmacao.valor, afirmacao.valor_base or ""
    tokens = content_tokens(valor)
    tokens_origem = set(content_tokens(origem))

    if not tokens:
        return _res(afirmacao, Veredito.NAO_VERIFICAVEL, 0.0, "DER-VAZIO")
    if not tokens_origem:
        return _res(afirmacao, Veredito.NAO_VERIFICAVEL, 0.0, "DER-BASE-INDISPONIVEL",
                    notas=[f"campo-base '{afirmacao.base_derivacao}' indisponível; vínculo não demonstrado"])

    novos = [tok for tok in dict.fromkeys(tokens) if tok not in tokens_origem]
    cobertura = 1.0 - (len(novos) / len(set(tokens)))

    numeros_origem: Set[Decimal] = set()
    for occ in iter_numbers(normalize(origem)):
        numeros_origem |= set(occ.values)
    numeros_novos = [occ.raw for occ in iter_numbers(normalize(valor))
                     if not (set(occ.values) & numeros_origem)]

    entidades_novas = sorted(_entidades(valor) - _entidades(origem) - tokens_origem)
    palavras = word_count(valor)

    evidencia = Evidence(
        rule="DER-BASE", score=cobertura, chunk_id=None,
        path=f"registro[{afirmacao.registro}].{afirmacao.base_derivacao}",
        kind="campo-base",
        snippet_before="", snippet_match=origem[:220] + ("…" if len(origem) > 220 else ""),
        snippet_after="", detail="base factual declarada para o campo derivado",
    )

    notas = [f"cobertura de {cobertura:.0%} em relação a "
             f"'{afirmacao.base_derivacao}' ({palavras} palavras)"]
    if novos:
        notas.append("termos não presentes na base: " + ", ".join(novos[:10]))
    if numeros_novos:
        notas.append("números ausentes da base: " + ", ".join(numeros_novos[:6]))
    if entidades_novas:
        notas.append("entidades introduzidas: " + ", ".join(entidades_novas[:6]))
    if palavras > config.resumo_max_palavras:
        notas.append(f"excede o limite de {config.resumo_max_palavras} palavras "
                     "definido no prompt de extração")

    if numeros_novos or entidades_novas:
        return _res(afirmacao, Veredito.NAO_SUPORTADA, 1.0, "DER-CONTEUDO-NOVO",
                    [evidencia], notas + ["o resumo introduz conteúdo factual "
                                          "ausente do campo de origem"],
                    novos, numeros_novos)
    negativos = {"nao", "nunca", "jamais", "not", "never", "sem", "without"}
    literal = bool(re.search(r"(?<!\w)" + re.escape(normalize(valor)) + r"(?!\w)", normalize(origem)))
    polaridade_igual = (set(tokenize(valor)) & negativos) == (set(tokenize(origem)) & negativos)
    if literal and polaridade_igual:
        return _res(afirmacao, Veredito.SUPORTADA, 1.0, "DER-VINCULADO",
                    [evidencia], notas + ["trecho literal da base, sem supressão de negação"])
    if cobertura >= 0.90:
        return _res(afirmacao, Veredito.PARCIAL, cobertura, "DER-VINCULO-PARCIAL",
                    [evidencia], notas + ["vocabulário comum não comprova equivalência factual"])
    if cobertura >= config.resumo_cobertura_minima:
        return _res(afirmacao, Veredito.PARCIAL, cobertura, "DER-VINCULO-PARCIAL",
                    [evidencia], notas + ["parte do vocabulário do resumo não deriva "
                                          "da base (possível paráfrase ou acréscimo)"],
                    novos)
    return _res(afirmacao, Veredito.NAO_SUPORTADA, 1.0 - cobertura, "DER-SEM-VINCULO",
                [evidencia], notas, novos, numeros_novos)
