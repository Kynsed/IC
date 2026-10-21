"""Acesso ao contrato compartilhado, inclusive ao executar a partir do subdiretório."""
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ic_contract import (ContractError, build_schema, canonical_json, loads_json,
                         parse_response, schema_sha256, validate_records, validate_schema)
