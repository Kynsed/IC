"""
Interface web da verificação neuro-simbólica.

Complementa a interface do `extraction_tool` (porta 5000): recebe o JSON/CSV
extraído e a fonte correspondente, executa o pipeline e devolve o relatório
com as evidências destacadas.

    python -m neurosimbolico servidor --porta 5001
"""

from __future__ import annotations

import json
import csv
from html import escape
import uuid
from pathlib import Path
from typing import Dict, Optional

from flask import Flask, abort, request, send_file

from .afirmacoes import ler_registros
from .contrato import loads_json
from .config import Config
from .relatorio import escrever_csv, escrever_html, escrever_json, gerar_html
from .verificador import Relatorio, verificar_dados

PASTA_SAIDA = Path(__file__).resolve().parent.parent / "relatorios" / "web"
_RELATORIOS: Dict[str, Relatorio] = {}

_FORMULARIO = """<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Verificação neuro-simbólica</title>
<style>
:root { color-scheme: light dark; --bg:#fff; --fg:#111827; --muted:#6b7280;
  --line:#e5e7eb; --card:#f9fafb; --accent:#1d4ed8; }
@media (prefers-color-scheme:dark){ :root{ --bg:#0f1115; --fg:#e5e7eb;
  --muted:#9ca3af; --line:#262b36; --card:#161a22; --accent:#7aa2ff; } }
*{box-sizing:border-box}
body{margin:0;padding:2.5rem 1.25rem;background:var(--bg);color:var(--fg);
  font:15px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
main{max-width:720px;margin:0 auto}
h1{font-size:1.5rem;margin:0 0 .3rem}
p.sub{color:var(--muted);font-size:.9rem;margin:0 0 2rem}
fieldset{border:1px solid var(--line);border-radius:10px;padding:1rem 1.1rem;
  margin:0 0 1.1rem;background:var(--card)}
legend{font-weight:650;font-size:.85rem;padding:0 .4rem}
label{display:block;font-size:.85rem;font-weight:600;margin:.7rem 0 .25rem}
input[type=file],input[type=text],textarea,select{width:100%;padding:.5rem;
  border:1px solid var(--line);border-radius:7px;background:var(--bg);
  color:var(--fg);font:inherit;font-size:.88rem}
textarea{min-height:110px;font-family:ui-monospace,Consolas,monospace;font-size:.8rem}
small{color:var(--muted);font-size:.78rem;display:block;margin-top:.2rem}
button{margin-top:.6rem;padding:.6rem 1.3rem;border:0;border-radius:8px;
  background:var(--accent);color:#fff;font:inherit;font-weight:650;cursor:pointer}
.erro{background:#fee2e2;color:#a4161a;padding:.7rem .9rem;border-radius:8px;
  margin-bottom:1.2rem;font-size:.88rem}
.linha{display:grid;grid-template-columns:1fr 1fr;gap:.9rem}
@media (max-width:620px){.linha{grid-template-columns:1fr}}
</style>
<main>
<h1>Verificação neuro-simbólica de extração</h1>
<p class="sub">Confronta as informações extraídas pelo <code>extraction_tool</code>
com a fonte original. Pipeline determinístico — sem BeautifulSoup e sem nova
chamada ao LLM.</p>
__ERRO__
<form method="post" action="/verificar" enctype="multipart/form-data">
  <fieldset><legend>1. Saída do extraction_tool</legend>
    <label>Arquivo <code>{task_id}_data.json</code> ou <code>.csv</code></label>
    <input type="file" name="extracao" accept=".json,.csv">
    <label>…ou cole o JSON extraído</label>
    <textarea name="extracao_texto" placeholder='[{"Título": "...", "Preço": "R$ 69,69"}]'></textarea>
  </fieldset>

  <fieldset><legend>2. Fonte original</legend>
    <label>HTML bruto da página ou <code>{task_id}_text.txt</code></label>
    <input type="file" name="fonte" accept=".html,.htm,.txt">
    <label>…ou cole o conteúdo da fonte</label>
    <textarea name="fonte_texto" placeholder="&lt;html&gt;…&lt;/html&gt; ou o texto limpo"></textarea>
    <small>Com o HTML bruto são aplicadas também as regras estruturais
    (localidade no DOM). Com o texto limpo, apenas as regras lexicais e de tipo.</small>
  </fieldset>

  <fieldset><legend>3. Opções</legend>
    <div class="linha">
      <div>
        <label>Tipo da fonte</label>
        <select name="tipo_fonte">
          <option value="">detecção automática</option>
          <option value="html">HTML</option>
          <option value="texto">texto limpo</option>
        </select>
      </div>
      <div>
        <label>Coesão mínima no DOM</label>
        <input type="text" name="coesao_minima" value="0.70">
      </div>
    </div>
    <label>Gabarito (opcional, JSON de anotação manual)</label>
    <input type="file" name="gabarito" accept=".json">
    <small>Habilita precisão/revocação/F1 da detecção de alucinações.</small>
    <label>Contrato JSON Schema (opcional)</label>
    <input type="file" name="schema" accept=".json">
    <small>Para conferir o manifesto e os hashes da execução, utilize a interface de linha de comando com os arquivos originais.</small>
  </fieldset>

  <button type="submit">Verificar</button>
</form>
</main>"""

_BARRA = """<div style="position:sticky;top:0;z-index:9;display:flex;gap:.75rem;
align-items:center;flex-wrap:wrap;padding:.6rem 1rem;margin:-2rem -1.25rem 1.5rem;
background:#111827;color:#e5e7eb;font:14px/1.4 -apple-system,Segoe UI,Roboto,sans-serif">
<a href="/" style="color:#93c5fd;text-decoration:none;font-weight:650">&larr; nova verificação</a>
<span style="margin-left:auto">baixar:</span>
<a href="/baixar/__ID__/json" style="color:#93c5fd">JSON</a>
<a href="/baixar/__ID__/csv" style="color:#93c5fd">CSV</a>
<a href="/baixar/__ID__/html" style="color:#93c5fd">HTML</a>
</div>"""


def _ler_entrada(campo_arquivo: str, campo_texto: str) -> Optional[str]:
    enviado = request.files.get(campo_arquivo)
    if enviado and enviado.filename:
        return enviado.read().decode("utf-8-sig")
    texto = (request.form.get(campo_texto) or "").strip()
    return texto or None


def criar_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)

    @app.get("/")
    def formulario():
        return _FORMULARIO.replace("__ERRO__", "")

    @app.post("/verificar")
    def executar():
        def erro(mensagem: str, codigo: int = 400):
            return _FORMULARIO.replace(
                "__ERRO__", f'<div class="erro">{escape(mensagem)}</div>'), codigo

        try:
            bruto_extracao = _ler_entrada("extracao", "extracao_texto")
            bruto_fonte = _ler_entrada("fonte", "fonte_texto")
        except UnicodeError:
            return erro("Os arquivos devem usar codificação UTF-8.")

        if not bruto_extracao:
            return erro("Informe o arquivo de extração ou cole o JSON correspondente.")
        if not bruto_fonte:
            return erro("Informe a fonte (HTML bruto ou texto limpo) da página.")

        try:
            enviado_schema = request.files.get("schema")
            schema = loads_json(enviado_schema.read().decode("utf-8-sig")) if enviado_schema and enviado_schema.filename else None
            enviado_extracao = request.files.get("extracao")
            formato = "csv" if enviado_extracao and Path(enviado_extracao.filename or "").suffix.lower() == ".csv" else "json"
            registros = ler_registros(bruto_extracao, formato, schema)
            config = Config()
            config.coesao_minima = float(request.form.get("coesao_minima") or 0.70)
            config.validate()
            gabarito = None
            enviado = request.files.get("gabarito")
            if enviado and enviado.filename:
                gabarito = loads_json(enviado.read().decode("utf-8-sig"))
            tipo_form = request.form.get("tipo_fonte") or ""
            if tipo_form not in ("", "html", "texto"):
                return erro("Tipo de fonte inválido.")
            tipo = {"html": "html", "texto": "text"}.get(tipo_form)
            relatorio = verificar_dados(
                registros, bruto_fonte, config=config, gabarito=gabarito,
                forcar_tipo_fonte=tipo, schema=schema,
                origem_extracao=(enviado_extracao.filename if enviado_extracao else "colado na interface"),
                origem_fonte=(request.files.get("fonte").filename
                              if request.files.get("fonte") else "colada na interface"),
            )
        except (ValueError, UnicodeError, csv.Error) as falha:
            return erro(f"Entrada inválida: {falha}")

        identificador = uuid.uuid4().hex[:12]
        _RELATORIOS[identificador] = relatorio
        escrever_json(relatorio, PASTA_SAIDA / f"{identificador}_verificacao.json")
        escrever_csv(relatorio, PASTA_SAIDA / f"{identificador}_afirmacoes.csv")
        escrever_html(relatorio, PASTA_SAIDA / f"{identificador}_relatorio.html")

        return _BARRA.replace("__ID__", identificador) + gerar_html(relatorio)

    @app.get("/baixar/<identificador>/<formato>")
    def baixar(identificador: str, formato: str):
        nomes = {
            "json": f"{identificador}_verificacao.json",
            "csv": f"{identificador}_afirmacoes.csv",
            "html": f"{identificador}_relatorio.html",
        }
        if formato not in nomes:
            abort(404)
        caminho = PASTA_SAIDA / nomes[formato]
        if not caminho.exists():
            abort(404)
        return send_file(caminho, as_attachment=True, download_name=nomes[formato])

    @app.get("/api/verificar")
    def ajuda_api():
        return {
            "uso": "POST /verificar com os campos 'extracao' e 'fonte' "
                   "(arquivo ou texto)",
            "relatorios_em_memoria": len(_RELATORIOS),
        }

    return app


app = None  # criado sob demanda por criar_app()


if __name__ == "__main__":
    criar_app().run(host="127.0.0.1", port=5001, debug=True)
