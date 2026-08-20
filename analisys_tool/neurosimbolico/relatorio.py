"""
Geração dos artefatos de saída da verificação.

Três formatos, três finalidades:

* JSON -- registro completo e auditável (entrada para análises posteriores);
* CSV  -- uma linha por afirmação, para planilhas e cálculo de métricas;
* HTML -- relatório de leitura humana, com a citação da fonte que sustenta
  cada veredito destacada no trecho original.
"""

from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path
from typing import Any, Dict, List

from .config import Veredito
from .verificador import Relatorio, RelatorioRegistro

__all__ = ["escrever_json", "escrever_csv", "escrever_html", "gerar_html", "resumo_texto"]

_CORES = {
    Veredito.SUPORTADA: ("#0f7b3f", "#dcfce7"),
    Veredito.PARCIAL: ("#8a5a00", "#fef3c7"),
    Veredito.NAO_SUPORTADA: ("#a4161a", "#fee2e2"),
    Veredito.ATRIBUICAO_INCORRETA: ("#9a3412", "#ffedd5"),
    Veredito.INVALIDA: ("#6b1d73", "#f5e0f7"),
    Veredito.ABSTENCAO: ("#475569", "#e2e8f0"),
    Veredito.ERRO_EXTRACAO: ("#475569", "#e2e8f0"),
    Veredito.NAO_VERIFICAVEL: ("#475569", "#e2e8f0"),
}
_ROTULO_NIVEL = {"ok": "íntegro", "atencao": "atenção", "critico": "crítico"}


# ---------------------------------------------------------------------------
# JSON / CSV
# ---------------------------------------------------------------------------

def escrever_json(relatorio: Relatorio, caminho: str | Path) -> Path:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(relatorio.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return caminho


def escrever_csv(relatorio: Relatorio, caminho: str | Path) -> Path:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    colunas = ["registro", "campo", "tipo", "valor", "veredito", "score", "regra",
               "caminho_evidencia", "trecho_evidencia", "notas",
               "sugestao_1", "confiabilidade_registro", "coesao_registro"]
    with caminho.open("w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=colunas, delimiter=";")
        escritor.writeheader()
        for bloco in relatorio.registros:
            for resultado in bloco.resultados:
                evidencia = resultado.evidencia_principal
                sugestoes = bloco.sugestoes.get(resultado.afirmacao.id, [])
                escritor.writerow({
                    "registro": resultado.afirmacao.registro,
                    "campo": resultado.afirmacao.campo,
                    "tipo": resultado.afirmacao.tipo,
                    "valor": resultado.afirmacao.valor,
                    "veredito": resultado.veredito,
                    "score": round(resultado.score, 4),
                    "regra": resultado.regra,
                    "caminho_evidencia": evidencia.path if evidencia else "",
                    "trecho_evidencia": (evidencia.snippet if evidencia else "")[:400],
                    "notas": " | ".join(resultado.notas),
                    "sugestao_1": sugestoes[0].valor if sugestoes else "",
                    "confiabilidade_registro": bloco.confiabilidade,
                    "coesao_registro": round(bloco.coesao.valor, 4),
                })
    return caminho


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_CSS = """
:root { color-scheme: light dark;
  --bg:#ffffff; --fg:#111827; --muted:#6b7280; --line:#e5e7eb; --card:#f9fafb;
  --accent:#1d4ed8; }
@media (prefers-color-scheme: dark) { :root {
  --bg:#0f1115; --fg:#e5e7eb; --muted:#9ca3af; --line:#262b36; --card:#161a22;
  --accent:#7aa2ff; } }
* { box-sizing:border-box; }
body { margin:0; padding:2rem 1.25rem 4rem; background:var(--bg); color:var(--fg);
  font:15px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }
main { max-width:1080px; margin:0 auto; }
h1 { font-size:1.6rem; margin:0 0 .25rem; }
h2 { font-size:1.15rem; margin:2.5rem 0 .75rem; padding-bottom:.35rem;
  border-bottom:1px solid var(--line); }
h3 { font-size:1rem; margin:0; }
.sub { color:var(--muted); font-size:.87rem; margin:0 0 1.5rem; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:.75rem; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:.85rem 1rem; }
.card .v { font-size:1.5rem; font-weight:650; }
.card .k { color:var(--muted); font-size:.78rem; text-transform:uppercase; letter-spacing:.04em; }
table { width:100%; min-width:700px; border-collapse:collapse; font-size:.88rem; }
.wrap { overflow-x:auto; }
td:nth-child(2) { min-width:170px; }
td:nth-child(5) { min-width:230px; }
th,td { text-align:left; padding:.5rem .6rem; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:600; font-size:.78rem; text-transform:uppercase; letter-spacing:.03em; }
.badge { display:inline-block; padding:.1rem .5rem; border-radius:999px; font-size:.74rem;
  font-weight:650; white-space:nowrap; }
.reg { border:1px solid var(--line); border-radius:10px; margin:.9rem 0; overflow:hidden; }
.reg > header { display:flex; align-items:center; gap:.6rem; flex-wrap:wrap;
  padding:.7rem .9rem; background:var(--card); border-bottom:1px solid var(--line); }
.reg > header .meta { color:var(--muted); font-size:.8rem; margin-left:auto; }
.ev { font-size:.82rem; color:var(--muted); }
.ev code { font-size:.74rem; overflow-wrap:anywhere; }
mark { background:#fde68a; color:#111827; padding:0 .1rem; border-radius:3px; }
.notas { margin:.3rem 0 0; padding-left:1.1rem; font-size:.8rem; color:var(--muted); }
.sug { font-size:.8rem; margin-top:.35rem; }
.sug b { color:var(--accent); }
.valor { font-weight:600; overflow-wrap:break-word; }
.viol { color:#a4161a; font-weight:600; }
.ok { color:#0f7b3f; }
footer { margin-top:3rem; color:var(--muted); font-size:.78rem; }
"""


def _badge(veredito: str) -> str:
    cor, fundo = _CORES.get(veredito, ("#475569", "#e2e8f0"))
    return (f'<span class="badge" style="color:{cor};background:{fundo}">'
            f'{escape(veredito.replace("_", " ").lower())}</span>')


def _evidencia_html(resultado) -> str:
    evidencia = resultado.evidencia_principal
    if evidencia is None:
        return '<div class="ev">sem evidência localizada</div>'
    trecho = (f'{escape(evidencia.snippet_before)}'
              f'<mark>{escape(evidencia.snippet_match)}</mark>'
              f'{escape(evidencia.snippet_after)}')
    return (f'<div class="ev">{trecho}<br><code>{escape(evidencia.path)}</code>'
            f' · <em>{escape(evidencia.kind)}</em></div>')


def _registro_html(bloco: RelatorioRegistro) -> str:
    partes: List[str] = []
    nivel = _ROTULO_NIVEL[bloco.nivel]
    cor = {"ok": "#0f7b3f", "atencao": "#8a5a00", "critico": "#a4161a"}[bloco.nivel]
    partes.append(
        f'<section class="reg"><header>'
        f'<h3>Registro {bloco.registro.indice}</h3>'
        f'<span class="badge" style="color:{cor};background:transparent;'
        f'border:1px solid {cor}">{nivel}</span>'
        f'<span class="meta">confiabilidade {bloco.confiabilidade:.2f}'
        f' · coesão no DOM {bloco.coesao.valor:.0%}'
        f'{" · âncora " + escape(bloco.coesao.caminho_ancora) if bloco.coesao.caminho_ancora else ""}'
        f'</span></header><div class="wrap"><table><thead><tr>'
        f'<th>Campo</th><th>Valor extraído</th><th>Veredito</th>'
        f'<th>Regra</th><th>Evidência na fonte</th></tr></thead><tbody>'
    )
    for resultado in bloco.resultados:
        notas = "".join(f"<li>{escape(n)}</li>" for n in resultado.notas)
        sugestoes = bloco.sugestoes.get(resultado.afirmacao.id, [])
        bloco_sug = ""
        if sugestoes:
            itens = " · ".join(
                f'<b>{escape(s.valor[:80])}</b> <span class="ev">({escape(s.justificativa)})</span>'
                for s in sugestoes)
            bloco_sug = f'<div class="sug">Correção ancorada sugerida: {itens}</div>'
        partes.append(
            f'<tr><td>{escape(resultado.afirmacao.campo)}<br>'
            f'<span class="ev">{escape(resultado.afirmacao.tipo)}</span></td>'
            f'<td class="valor">{escape(resultado.afirmacao.valor[:280])}'
            f'{"…" if len(resultado.afirmacao.valor) > 280 else ""}{bloco_sug}</td>'
            f'<td>{_badge(resultado.veredito)}<br>'
            f'<span class="ev">score {resultado.score:.2f}</span></td>'
            f'<td><code>{escape(resultado.regra)}</code></td>'
            f'<td>{_evidencia_html(resultado)}'
            f'{f"<ul class=notas>{notas}</ul>" if notas else ""}</td></tr>'
        )
    partes.append("</tbody></table></div>")

    violadas = [r for r in bloco.restricoes if r.violada]
    if violadas:
        itens = "".join(
            f'<li><code>{escape(r.id)}</code> ({escape(r.severidade)}) — {escape(r.mensagem)}</li>'
            for r in violadas)
        partes.append(f'<div style="padding:.6rem .9rem"><span class="viol">'
                      f'Restrições violadas</span><ul class="notas">{itens}</ul></div>')
    partes.append("</section>")
    return "".join(partes)


def gerar_html(relatorio: Relatorio) -> str:
    """Relatório autocontido (sem dependências externas)."""
    m = relatorio.metricas
    cards = [
        ("Afirmações", m["total_afirmacoes"]),
        ("Verificáveis", m["afirmacoes_verificaveis"]),
        ("Taxa de ancoragem", f'{m["taxa_ancoragem"]:.0%}'),
        ("Taxa de alucinação", f'{m["taxa_alucinacao"]:.0%}'),
        ("Suporte parcial", f'{m["taxa_suporte_parcial"]:.0%}'),
        ("Abstenção", f'{m["taxa_abstencao"]:.0%}'),
        ("Confiabilidade média", f'{m["confiabilidade_media"]:.2f}'),
        ("Restrições violadas", m["restricoes_violadas_total"]),
    ]
    html_cards = "".join(
        f'<div class="card"><div class="k">{escape(k)}</div><div class="v">{escape(str(v))}</div></div>'
        for k, v in cards)

    linhas_campo = "".join(
        f'<tr><td>{escape(campo)}</td><td>{dados["total"]}</td>'
        f'<td>{dados["taxa_ancoragem"]:.0%}</td>'
        f'<td class="{"viol" if dados["taxa_alucinacao"] else "ok"}">'
        f'{dados["taxa_alucinacao"]:.0%}</td>'
        f'<td class="ev">{escape(", ".join(f"{k.lower()}: {v}" for k, v in dados["vereditos"].items()))}</td></tr>'
        for campo, dados in m["por_campo"].items())

    conjunto = "".join(
        f'<li><code>{escape(r.id)}</code> — <span class="{"viol" if r.violada else "ok"}">'
        f'{escape(r.status)}</span>: {escape(r.mensagem)}</li>'
        for r in relatorio.restricoes_conjunto)

    avaliacao = ""
    if relatorio.avaliacao_gabarito and "permissivo" in relatorio.avaliacao_gabarito:
        linhas = ""
        for regime in ("permissivo", "estrito"):
            d = relatorio.avaliacao_gabarito[regime]
            linhas += (f'<tr><td>{regime}</td><td>{d["precisao"]:.2f}</td>'
                       f'<td>{d["revocacao"]:.2f}</td><td>{d["f1"]:.2f}</td>'
                       f'<td>{d["acuracia"]:.2f}</td>'
                       f'<td class="ev">VP {d["verdadeiros_positivos"]} · '
                       f'FP {d["falsos_positivos"]} · FN {d["falsos_negativos"]} · '
                       f'VN {d["verdadeiros_negativos"]}</td></tr>')
        avaliacao = (
            '<h2>Avaliação do verificador (gabarito)</h2><div class="wrap"><table><thead><tr>'
            '<th>Regime</th><th>Precisão</th><th>Revocação</th><th>F1</th>'
            '<th>Acurácia</th><th>Matriz</th></tr></thead>'
            f'<tbody>{linhas}</tbody></table></div>'
            f'<p class="sub">{relatorio.avaliacao_gabarito["afirmacoes_anotadas"]} '
            'afirmações anotadas. Classe positiva: afirmação incorreta.</p>')

    registros = "".join(_registro_html(bloco) for bloco in relatorio.registros)

    return f"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Verificação neuro-simbólica — relatório</title>
<style>{_CSS}</style>
<main>
<h1>Verificação neuro-simbólica de extração</h1>
<p class="sub">
  Extração: <code>{escape(relatorio.origem_extracao)}</code> ·
  Fonte: <code>{escape(relatorio.origem_fonte)}</code> ({escape(relatorio.modo_fonte)}) ·
  {escape(relatorio.descricao_indice)} · gerado em {escape(relatorio.gerado_em)}
</p>
<div class="cards">{html_cards}</div>

<h2>Factualidade por campo</h2>
<div class="wrap"><table><thead><tr><th>Campo</th><th>Afirmações</th>
<th>Ancoragem</th><th>Alucinação</th><th>Distribuição</th></tr></thead>
<tbody>{linhas_campo}</tbody></table></div>

<h2>Restrições de conjunto</h2>
<ul class="notas">{conjunto or "<li>nenhuma restrição de conjunto aplicável</li>"}</ul>

{avaliacao}

<h2>Registros verificados</h2>
{registros}

<footer>
Pipeline determinístico: indexação da fonte via <code>html.parser</code> (stdlib),
sem BeautifulSoup e sem consulta a modelo neural na etapa de verificação.
Cada veredito referencia a regra que o produziu e o trecho da fonte que o sustenta.
</footer>
</main>"""


def escrever_html(relatorio: Relatorio, caminho: str | Path) -> Path:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(gerar_html(relatorio), encoding="utf-8")
    return caminho


# ---------------------------------------------------------------------------
# Console
# ---------------------------------------------------------------------------

def resumo_texto(relatorio: Relatorio, detalhado: bool = False) -> str:
    """Resumo legível para o terminal."""
    m = relatorio.metricas
    linhas: List[str] = []
    linhas.append("=" * 74)
    linhas.append("VERIFICACAO NEURO-SIMBOLICA — RESUMO")
    linhas.append("=" * 74)
    linhas.append(f"Extração : {relatorio.origem_extracao}")
    linhas.append(f"Fonte    : {relatorio.origem_fonte}  [{relatorio.modo_fonte}] "
                  f"({relatorio.descricao_indice})")
    linhas.append("-" * 74)
    linhas.append(f"Registros ................ {m['total_registros']}")
    linhas.append(f"Afirmações ............... {m['total_afirmacoes']} "
                  f"({m['afirmacoes_verificaveis']} verificáveis)")
    for veredito, quantidade in m["vereditos"].items():
        if quantidade:
            linhas.append(f"  {veredito:<18} {quantidade}")
    linhas.append("-" * 74)
    linhas.append(f"Taxa de ancoragem ........ {m['taxa_ancoragem']:.1%}")
    linhas.append(f"Taxa de suporte parcial .. {m['taxa_suporte_parcial']:.1%}")
    linhas.append(f"Taxa de alucinação ....... {m['taxa_alucinacao']:.1%}")
    linhas.append(f"Taxa de abstenção ........ {m['taxa_abstencao']:.1%}")
    linhas.append(f"Confiabilidade média ..... {m['confiabilidade_media']:.2f}")
    linhas.append(f"Restrições violadas ...... {m['restricoes_violadas_total']} "
                  f"{dict(m['restricoes_violadas']) or ''}")

    problemas = [r for r in relatorio.afirmacoes if r.alucinacao]
    if problemas:
        linhas.append("-" * 74)
        linhas.append(f"AFIRMAÇÕES REPROVADAS ({len(problemas)}):")
        for resultado in problemas[:40]:
            afirmacao = resultado.afirmacao
            linhas.append(f"  [{resultado.veredito}] r{afirmacao.registro}."
                          f"{afirmacao.campo} = {afirmacao.valor[:70]!r}")
            # a nota que justifica o veredito é a última quando ele foi
            # rebaixado por localidade, e a primeira nos demais casos
            nota = ""
            if resultado.notas:
                bruta = (resultado.notas[-1]
                         if resultado.veredito == Veredito.ATRIBUICAO_INCORRETA
                         else resultado.notas[0])
                nota = " | " + (bruta[:150] + "…" if len(bruta) > 150 else bruta)
            linhas.append(f"      regra {resultado.regra}{nota}")
    violadas = [r for bloco in relatorio.registros for r in bloco.restricoes if r.violada]
    violadas += [r for r in relatorio.restricoes_conjunto if r.violada]
    if violadas:
        linhas.append("-" * 74)
        linhas.append(f"RESTRIÇÕES VIOLADAS ({len(violadas)}):")
        for restricao in violadas[:25]:
            alvo = f"r{restricao.registro}" if restricao.registro is not None else "conjunto"
            linhas.append(f"  [{restricao.severidade}] {restricao.id} ({alvo}): "
                          f"{restricao.mensagem}")

    if relatorio.avaliacao_gabarito and "permissivo" in relatorio.avaliacao_gabarito:
        d = relatorio.avaliacao_gabarito["permissivo"]
        linhas.append("-" * 74)
        linhas.append("DETECÇÃO DE ALUCINAÇÕES vs GABARITO (regime permissivo):")
        linhas.append(f"  precisão {d['precisao']:.2f} | revocação {d['revocacao']:.2f} "
                      f"| F1 {d['f1']:.2f} | acurácia {d['acuracia']:.2f}")
    linhas.append("=" * 74)
    return "\n".join(linhas)
