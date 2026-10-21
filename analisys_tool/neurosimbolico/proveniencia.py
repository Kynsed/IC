"""Validação dos artefatos imutáveis de uma execução do extrator."""
import hashlib
from pathlib import Path

from .contrato import ContractError, loads_json, schema_sha256, validate_schema


def sha256(dados):
    return hashlib.sha256(dados).hexdigest()


def carregar_manifesto(extracao, fonte, schema=None):
    extracao, fonte = Path(extracao).resolve(), Path(fonte).resolve()
    task_id = extracao.stem.removesuffix("_data")
    caminho = extracao.with_name(f"{task_id}_manifest.json")
    if not caminho.exists():
        return schema, {"estado": "legado_sem_manifesto", "execucao_id": None,
                        "extracao_sha256": sha256(extracao.read_bytes()),
                        "fonte_sha256": sha256(fonte.read_bytes())}
    manifesto = loads_json(caminho.read_text(encoding="utf-8-sig"))
    if (not isinstance(manifesto, dict) or manifesto.get("manifest_version") != 1
            or manifesto.get("status") != "completed" or manifesto.get("task_id") != task_id):
        raise ContractError("Manifesto incompatível ou execução não concluída.")
    contrato = manifesto.get("schema")
    validate_schema(contrato)
    if manifesto.get("schema_sha256") != schema_sha256(contrato):
        raise ContractError("Hash do contrato difere do manifesto.")
    if schema is not None and schema_sha256(schema) != schema_sha256(contrato):
        raise ContractError("Contrato informado difere do contrato da execução.")
    artefatos = {}
    for nome in ("source", "processed_input", "prompt", "raw_response", "extraction"):
        item = manifesto.get(nome)
        if item is None and nome == "processed_input":
            continue
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ContractError(f"Artefato ausente no manifesto: {nome}")
        relativo = Path(item["path"])
        arquivo = (caminho.parent / relativo).resolve()
        if relativo.is_absolute() or not arquivo.is_relative_to(caminho.parent):
            raise ContractError(f"Caminho inválido no manifesto: {nome}")
        if not arquivo.is_file() or sha256(arquivo.read_bytes()) != item.get("sha256"):
            raise ContractError(f"Artefato ausente ou hash divergente: {nome}")
        artefatos[nome] = arquivo
    if manifesto["source"].get("kind") != "html":
        raise ContractError("Fonte de imagem preservada, mas este verificador exige HTML/texto; OCR não implementado.")
    if artefatos["source"] != fonte or artefatos["extraction"] != extracao:
        raise ContractError("Extração/fonte selecionadas não são o par original do manifesto; use o JSON e o HTML registrados.")
    return contrato, {"estado": "manifesto_validado", "execucao_id": task_id,
                      "manifesto": str(caminho), "manifesto_sha256": sha256(caminho.read_bytes()),
                      "extracao_sha256": manifesto["extraction"]["sha256"],
                      "fonte_sha256": manifesto["source"]["sha256"],
                      "schema_sha256": schema_sha256(contrato),
                      "provider": manifesto.get("provider", {})}
