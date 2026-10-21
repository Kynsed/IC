"""Contrato JSON compartilhado pelo extrator e verificador (somente stdlib).

Implementa um subconjunto explícito de JSON Schema 2020-12. Keywords fora
desse subconjunto são rejeitadas, nunca silenciosamente ignoradas. Não há
coerção, preenchimento de defaults ou correção semântica da resposta.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

CONTRACT_VERSION = 1
_TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}
_KEYWORDS = {"$schema", "$id", "title", "description", "type", "properties",
             "required", "additionalProperties", "items", "enum", "const",
             "minItems", "maxItems", "minLength", "maxLength", "minimum",
             "maximum", "pattern", "x-entity-key", "x-source-labels"}


class ContractError(ValueError):
    """Entrada ou resposta não satisfaz o contrato declarado."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def schema_sha256(schema: dict) -> str:
    return hashlib.sha256(canonical_json(schema).encode("utf-8")).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"Chave JSON duplicada: {key!r}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ContractError(f"Constante não JSON: {value}")


def _finite(value):
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _json_equal(left, right):
    # JSON Schema considera 1 e 1.0 o mesmo número, mas nunca true e 1.
    if type(left) in (int, float) and type(right) in (int, float):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_json_equal(left[k], right[k]) for k in left)
    return left == right


def loads_json(text: str) -> Any:
    try:
        return json.loads(text.lstrip("\ufeff"), object_pairs_hook=_pairs,
                          parse_constant=_invalid_constant)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ContractError(f"JSON inválido: {exc}") from exc


def build_schema(fields, include_summary: bool = True) -> dict:
    if not isinstance(fields, (list, tuple)) or not fields:
        raise ContractError("Informe pelo menos um campo.")
    names = []
    for field in fields:
        if not isinstance(field, str) or not field.strip() or field != field.strip():
            raise ContractError("Nomes de campo devem ser strings não vazias, sem espaços nas pontas.")
        if field in names:
            raise ContractError(f"Campo duplicado: {field}")
        names.append(field)
    if include_summary and any(n.casefold() in {
            "descrição", "descricao", "description", "detalhes", "details"} for n in names):
        if not any(n.casefold() in {"resumo", "summary"} for n in names):
            names.append("Resumo")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "array",
        "items": {
            "type": "object",
            "properties": {name: {"type": ["string", "number", "boolean", "null"]}
                           for name in names},
            "required": names,
            "additionalProperties": False,
        },
    }


def validate_schema(schema: dict) -> None:
    def visit(node, path):
        if not isinstance(node, dict):
            raise ContractError(f"{path}: schema deve ser objeto.")
        unknown = set(node) - _KEYWORDS
        if unknown:
            raise ContractError(f"{path}: keywords não suportadas: {sorted(unknown)}")
        types = node.get("type")
        types = [types] if isinstance(types, str) else types
        if (not isinstance(types, list) or not types or
                any(not isinstance(t, str) or t not in _TYPES for t in types) or
                len(types) != len(set(types))):
            raise ContractError(f"{path}: type inválido ou ausente.")
        if "$schema" in node and node["$schema"] != "https://json-schema.org/draft/2020-12/schema":
            raise ContractError(f"{path}: apenas o dialeto 2020-12 declarado é aceito.")
        if "object" in types:
            props = node.get("properties")
            if not isinstance(props, dict) or any(not isinstance(k, str) or not k for k in props):
                raise ContractError(f"{path}: properties deve conter nomes explícitos.")
            if node.get("additionalProperties") is not False:
                raise ContractError(f"{path}: additionalProperties deve ser false.")
            required = node.get("required", [])
            if (not isinstance(required, list) or any(not isinstance(k, str) for k in required)
                    or len(required) != len(set(required)) or not set(required) <= set(props)):
                raise ContractError(f"{path}: required inválido.")
            for key, value in props.items():
                visit(value, f"{path}/properties/{key}")
        elif any(k in node for k in ("properties", "required", "additionalProperties")):
            raise ContractError(f"{path}: keywords de objeto sem type object.")
        if "array" in types:
            if "items" not in node:
                raise ContractError(f"{path}: array exige items.")
            visit(node["items"], f"{path}/items")
        elif "items" in node:
            raise ContractError(f"{path}: items sem type array.")
        for key in ("minItems", "maxItems", "minLength", "maxLength"):
            if key in node and (type(node[key]) is not int or node[key] < 0):
                raise ContractError(f"{path}: {key} deve ser inteiro não negativo.")
        for key in ("minimum", "maximum"):
            if key in node and not _finite(node[key]):
                raise ContractError(f"{path}: {key} deve ser número finito.")
        for low, high in (("minItems", "maxItems"), ("minLength", "maxLength"), ("minimum", "maximum")):
            if low in node and high in node and node[low] > node[high]:
                raise ContractError(f"{path}: intervalo {low}/{high} inválido.")
        if "enum" in node and (not isinstance(node["enum"], list) or not node["enum"]):
            raise ContractError(f"{path}: enum deve ser lista não vazia.")
        if "pattern" in node:
            try:
                re.compile(node["pattern"])
            except (TypeError, re.error) as exc:
                raise ContractError(f"{path}: pattern inválido.") from exc
        if "x-entity-key" in node and type(node["x-entity-key"]) is not bool:
            raise ContractError(f"{path}: x-entity-key deve ser booleano.")
        if "x-source-labels" in node and (not isinstance(node["x-source-labels"], list)
                or any(not isinstance(s, str) or not s.strip() for s in node["x-source-labels"])):
            raise ContractError(f"{path}: x-source-labels deve ser lista de rótulos.")
        # Também rejeita valores não JSON dentro de enum/const/metadados.
        try:
            canonical_json(node)
        except (TypeError, ValueError) as exc:
            raise ContractError(f"{path}: schema contém valor não JSON.") from exc

    visit(schema, "schema")
    if schema.get("type") != "array" or schema.get("items", {}).get("type") != "object":
        raise ContractError("O contrato de extração deve ser array de objetos.")


def _matches_type(value, kind):
    return {
        "null": value is None,
        "boolean": type(value) is bool,
        "integer": type(value) is int or (type(value) is float and math.isfinite(value) and value.is_integer()),
        "number": _finite(value),
        "string": isinstance(value, str),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }[kind]


def validate_records(records, schema: dict) -> None:
    validate_schema(schema)

    def visit(value, node, path):
        kinds = node["type"] if isinstance(node["type"], list) else [node["type"]]
        if not any(_matches_type(value, kind) for kind in kinds):
            raise ContractError(f"{path}: esperado {kinds}; recebido {type(value).__name__}.")
        try:
            encoded = canonical_json(value)
        except (TypeError, ValueError) as exc:
            raise ContractError(f"{path}: valor não JSON.") from exc
        if "enum" in node and not any(_json_equal(value, item) for item in node["enum"]):
            raise ContractError(f"{path}: valor fora de enum.")
        if "const" in node and not _json_equal(value, node["const"]):
            raise ContractError(f"{path}: valor difere de const.")
        if isinstance(value, dict):
            props = node["properties"]
            missing, extra = set(node.get("required", [])) - set(value), set(value) - set(props)
            if missing or extra:
                raise ContractError(f"{path}: campos ausentes={sorted(missing)}, extras={sorted(extra)}.")
            for key, item in value.items():
                visit(item, props[key], f"{path}/{key}")
        elif isinstance(value, list):
            if len(value) < node.get("minItems", 0) or len(value) > node.get("maxItems", float("inf")):
                raise ContractError(f"{path}: cardinalidade fora do contrato.")
            for index, item in enumerate(value):
                visit(item, node["items"], f"{path}/{index}")
        elif isinstance(value, str):
            if len(value) < node.get("minLength", 0) or len(value) > node.get("maxLength", float("inf")):
                raise ContractError(f"{path}: tamanho da string fora do contrato.")
            if "pattern" in node and re.search(node["pattern"], value) is None:
                raise ContractError(f"{path}: string não satisfaz pattern.")
        elif type(value) in (int, float):
            if value < node.get("minimum", -float("inf")) or value > node.get("maximum", float("inf")):
                raise ContractError(f"{path}: número fora do contrato.")

    visit(records, schema, "registros")


def parse_response(raw: str, schema: dict) -> list[dict]:
    if not isinstance(raw, str) or not raw.strip():
        raise ContractError("Resposta vazia ou não textual.")
    text = raw.strip()
    fence = re.fullmatch(r"```(?:json)?\s*\n([\s\S]*?)\n```", text, flags=re.IGNORECASE)
    if fence:
        text = fence.group(1)
    records = loads_json(text)
    validate_records(records, schema)
    return records
