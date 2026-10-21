"""Executa o benchmark sintético local, sem rede nem chamadas ao LLM."""

import argparse
import json
from pathlib import Path

from neurosimbolico.avaliacao import format_benchmark, run_benchmark


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, help="Corpus JSON versionado; padrão benchmark/corpus_v1.json")
    parser.add_argument("--json", type=Path, help="Gravar relatório completo JSON neste arquivo")
    parser.add_argument("--texto", type=Path, help="Gravar resumo textual neste arquivo")
    args = parser.parse_args()
    result = run_benchmark(args.corpus)
    summary = format_benchmark(result)
    print(summary, end="")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.texto:
        args.texto.parent.mkdir(parents=True, exist_ok=True)
        args.texto.write_text(summary, encoding="utf-8")
    # Divergências científicas são resultados, não falhas de execução.
    return 1 if result["execution_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
