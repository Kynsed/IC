"""
Atalho de execução do verificador neuro-simbólico.

    python verificar.py verificar --extracao exemplos/extracao_llm.json \
                                  --fonte exemplos/pagina_livraria.html
    python verificar.py lote --dir ../extraction_tool/results
    python verificar.py servidor --porta 5001

Equivalente a `python -m neurosimbolico ...`, sem exigir que o pacote esteja
instalado nem que o diretório esteja no PYTHONPATH.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from neurosimbolico.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
