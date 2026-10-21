"""
Interface de linha de comando do verificador neuro-simbólico.

    python -m neurosimbolico verificar --extracao dados.json --fonte pagina.html
    python -m neurosimbolico lote --dir ../extraction_tool/results
    python -m neurosimbolico servidor --porta 5001
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .afirmacoes import carregar_registros
from .config import Config
from .relatorio import escrever_csv, escrever_html, escrever_json, resumo_texto
from .reparo import aplicar_reparos
from .verificador import Relatorio, verificar, reparar_e_reverificar
from .contrato import loads_json

FORMATOS = ("json", "csv", "html")


def _preparar_console() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _carregar_gabarito(caminho: Optional[str]) -> Any:
    if not caminho:
        return None
    return loads_json(Path(caminho).read_text(encoding="utf-8-sig"))


def _gerar_saidas(relatorio: Relatorio, destino: Path, base_nome: str,
                  formatos: List[str]) -> List[Path]:
    destino.mkdir(parents=True, exist_ok=True)
    gerados: List[Path] = []
    if "json" in formatos:
        gerados.append(escrever_json(relatorio, destino / f"{base_nome}_verificacao.json"))
    if "csv" in formatos:
        gerados.append(escrever_csv(relatorio, destino / f"{base_nome}_afirmacoes.csv"))
    if "html" in formatos:
        gerados.append(escrever_html(relatorio, destino / f"{base_nome}_relatorio.html"))
    return gerados


# ---------------------------------------------------------------------------
# comando: verificar
# ---------------------------------------------------------------------------

def comando_verificar(args: argparse.Namespace) -> int:
    config = Config.from_file(args.config) if args.config else Config()
    if args.coesao_minima is not None:
        config.coesao_minima = args.coesao_minima
    if args.resumo_max_palavras is not None:
        config.resumo_max_palavras = args.resumo_max_palavras

    relatorio = verificar(
        extracao=args.extracao,
        fonte=args.fonte,
        config=config,
        gabarito=_carregar_gabarito(args.gabarito),
        com_reparo=not args.sem_reparo,
        forcar_tipo_fonte={"html": "html", "texto": "text"}.get(args.tipo_fonte),
        schema=_carregar_gabarito(args.schema),
    )

    print(resumo_texto(relatorio))

    destino = Path(args.saida)
    base_nome = Path(args.extracao).stem
    formatos = [f.strip() for f in args.formato.split(",") if f.strip() in FORMATOS]
    for caminho in _gerar_saidas(relatorio, destino, base_nome, formatos):
        print(f"[saída] {caminho}")

    if args.aplicar_reparos:
        corrigidos, pos, mudancas = reparar_e_reverificar(relatorio, Path(args.fonte).read_text(encoding="utf-8-sig"))
        destino.mkdir(parents=True, exist_ok=True)
        caminho = destino / f"{base_nome}_corrigido.json"
        caminho.write_text(json.dumps(corrigidos, ensure_ascii=False, indent=2),
                           encoding="utf-8")
        escrever_json(pos, destino / f"{base_nome}_pos_reparo.json")
        auditoria = {"tentativas": mudancas, "metricas_antes": relatorio.metricas,
                     "metricas_depois": pos.metricas,
                     "nota": "Taxas do verificador não demonstram acurácia; avaliar com gabarito independente."}
        (destino / f"{base_nome}_reparos.json").write_text(json.dumps(auditoria, ensure_ascii=False, indent=2), encoding="utf-8")
        aceitos = sum(m["aceito"] for m in mudancas)
        print(f"[saída] {caminho}  ({aceitos} alteração(ões) aceita(s) após reverificação; veja *_reparos.json e *_pos_reparo.json)")

    if args.falhar_se_alucinacao and relatorio.alucinacoes:
        return 1
    return 0


# ---------------------------------------------------------------------------
# comando: lote
# ---------------------------------------------------------------------------

def _parear_resultados(diretorio: Path) -> List[Tuple[str, Path, Path]]:
    """
    Pareia os artefatos do extraction_tool: `{task_id}_data.json` com
    `{task_id}.html` (se existir) ou `{task_id}_text.txt`.
    """
    pares: List[Tuple[str, Path, Path]] = []
    for extracao in sorted(diretorio.glob("*_data.json")):
        task_id = extracao.name[: -len("_data.json")]
        candidatos = [
            diretorio / f"{task_id}.html",
            diretorio / f"{task_id}_source.html",
            diretorio / f"{task_id}_raw.html",
            diretorio / f"{task_id}_text.txt",
        ]
        fonte = next((c for c in candidatos if c.exists()), None)
        if fonte is not None:
            pares.append((task_id, extracao, fonte))
    return pares


def comando_lote(args: argparse.Namespace) -> int:
    diretorio = Path(args.dir)
    if not diretorio.is_dir():
        print(f"diretório inexistente: {diretorio}", file=sys.stderr)
        return 2

    pares = _parear_resultados(diretorio)
    if not pares:
        print(f"nenhum par (*_data.json + fonte) encontrado em {diretorio}",
              file=sys.stderr)
        return 2

    config = Config.from_file(args.config) if args.config else Config()
    destino = Path(args.saida)
    formatos = [f.strip() for f in args.formato.split(",") if f.strip() in FORMATOS]
    consolidado: List[Dict[str, Any]] = []

    for task_id, extracao, fonte in pares:
        relatorio = verificar(extracao, fonte, config=config,
                              com_reparo=not args.sem_reparo)
        _gerar_saidas(relatorio, destino, task_id, formatos)
        m = relatorio.metricas
        consolidado.append({
            "task_id": task_id,
            "fonte": fonte.name,
            "modo_fonte": relatorio.modo_fonte,
            "registros": m["total_registros"],
            "afirmacoes": m["total_afirmacoes"],
            "taxa_ancoragem": m["taxa_ancoragem"],
            "taxa_alucinacao": m["taxa_alucinacao"],
            "taxa_abstencao": m["taxa_abstencao"],
            "confiabilidade_media": m["confiabilidade_media"],
            "restricoes_violadas": m["restricoes_violadas_total"],
        })
        print(f"{task_id}: ancoragem {m['taxa_ancoragem']:.1%} | "
              f"alucinação {m['taxa_alucinacao']:.1%} | "
              f"restrições violadas {m['restricoes_violadas_total']}")

    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / "consolidado.json"
    caminho.write_text(json.dumps(consolidado, ensure_ascii=False, indent=2),
                       encoding="utf-8")

    import csv as _csv
    caminho_csv = destino / "consolidado.csv"
    with caminho_csv.open("w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = _csv.DictWriter(arquivo, fieldnames=list(consolidado[0]), delimiter=";")
        escritor.writeheader()
        escritor.writerows(consolidado)

    media = sum(linha["taxa_alucinacao"] for linha in consolidado) / len(consolidado)
    print("-" * 60)
    print(f"{len(consolidado)} extração(ões) verificada(s) | "
          f"taxa média de alucinação {media:.1%}")
    print(f"[saída] {caminho}")
    print(f"[saída] {caminho_csv}")
    return 0


# ---------------------------------------------------------------------------
# comando: servidor
# ---------------------------------------------------------------------------

def comando_servidor(args: argparse.Namespace) -> int:
    try:
        from .servidor import criar_app
    except ImportError as erro:
        print(f"interface web indisponível: {erro}\n"
              "instale o Flask com: pip install flask", file=sys.stderr)
        return 2
    criar_app().run(host=args.host, port=args.porta, debug=args.debug)
    return 0


# ---------------------------------------------------------------------------

def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="neurosimbolico",
        description="Verificação factual neuro-simbólica de extrações por LLM "
                    "(pipeline determinístico, sem BeautifulSoup).",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    comum = argparse.ArgumentParser(add_help=False)
    comum.add_argument("--saida", default="relatorios", help="diretório de saída")
    comum.add_argument("--formato", default="json,csv,html",
                       help="formatos separados por vírgula: json,csv,html")
    comum.add_argument("--config", help="JSON com limiares (ver Config)")
    comum.add_argument("--sem-reparo", action="store_true",
                       help="não calcular sugestões de correção")

    p_ver = sub.add_parser("verificar", parents=[comum],
                           help="verifica uma extração contra sua fonte")
    p_ver.add_argument("--extracao", required=True,
                       help="{task_id}_data.json ou .csv do extraction_tool")
    p_ver.add_argument("--fonte", required=True,
                       help="HTML bruto da página ou {task_id}_text.txt")
    p_ver.add_argument("--gabarito", help="JSON de anotação manual para avaliar o verificador")
    p_ver.add_argument("--schema", help="Contrato JSON Schema; validado automaticamente se houver manifesto")
    p_ver.add_argument("--tipo-fonte", choices=("html", "texto"),
                       help="força o tipo da fonte (padrão: detecção automática)")
    p_ver.add_argument("--aplicar-reparos", action="store_true",
                       help="grava um JSON corrigido com as sugestões ancoradas")
    p_ver.add_argument("--coesao-minima", type=float,
                       help="limiar da regra R-COESAO-DOM (padrão 0.70)")
    p_ver.add_argument("--resumo-max-palavras", type=int,
                       help="limite de palavras do campo derivado (padrão 30)")
    p_ver.add_argument("--falhar-se-alucinacao", action="store_true",
                       help="encerra com código 1 se houver afirmação reprovada")
    p_ver.set_defaults(func=comando_verificar)

    p_lote = sub.add_parser("lote", parents=[comum],
                            help="verifica todos os resultados de um diretório")
    p_lote.add_argument("--dir", required=True,
                        help="diretório results/ do extraction_tool")
    p_lote.set_defaults(func=comando_lote)

    p_srv = sub.add_parser("servidor", help="interface web de verificação")
    p_srv.add_argument("--porta", type=int, default=5001)
    p_srv.add_argument("--host", default="127.0.0.1")
    p_srv.add_argument("--debug", action="store_true")
    p_srv.set_defaults(func=comando_servidor)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    _preparar_console()
    args = construir_parser().parse_args(argv)
    if getattr(args, "sem_reparo", False) and getattr(args, "aplicar_reparos", False):
        print("--sem-reparo e --aplicar-reparos são incompatíveis.", file=sys.stderr)
        return 2
    try:
        return args.func(args)
    except (ValueError, OSError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
