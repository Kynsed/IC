"""Avaliação independente dos fatos extraídos, do detector e dos reparos.

Este módulo NÃO usa matching, normalização, tipos inferidos ou vereditos para
construir o gabarito. Fatos são folhas JSON identificadas por entidade e caminho.
O protocolo é exact-match tipado: formas normalizadas aceitas devem constar
explicitamente do gabarito. A avaliação não prova equivalência semântica geral.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


CLASSES_FACTUAIS = ("SUPORTADA", "ATRIBUICAO_INCORRETA", "NAO_SUPORTADA")
DECISOES_ADICIONAIS = ("ABSTENCAO", "PARCIAL", "NAO_VERIFICAVEL", "INVALIDA", "ERRO_EXTRACAO")
DECISOES = CLASSES_FACTUAIS + DECISOES_ADICIONAIS
ABSTENCOES = {"", "não disponível", "nao disponivel", "n/a", "não informado", "nao informado"}
CORPUS_PADRAO = Path(__file__).resolve().parent.parent / "benchmark" / "corpus_v1.json"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _is_absent(value: Any) -> bool:
    return value is None or isinstance(value, str) and value.strip().casefold() in ABSTENCOES


def _scalar(value: Any) -> str:
    if not isinstance(value, (str, int, float, bool)) and value is not None:
        raise ValueError("Folha factual deve ser um escalar JSON")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("NaN e infinito não são valores factuais JSON")
    # JSON distingue bool de int e preserva a representação int/float.
    return _json(value)


def _pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _records(records: Any, label: str) -> list[dict]:
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise ValueError(f"{label} deve ser uma lista de objetos JSON")
    for record in records:
        if any(not isinstance(key, str) for key in record):
            raise ValueError(f"{label}: nomes de campo devem ser strings")
    return records


def _keys(expected: list[dict], entity_keys: Any) -> dict[str, tuple[str, ...]]:
    """Chaves por coleção; '/' é a coleção de registros de nível superior."""
    if entity_keys is None:
        candidates = ("id", "nome", "name", "Título", "titulo", "title")
        for key in candidates:
            if expected and all(key in r and not _is_absent(r[key]) for r in expected):
                values = [_scalar(r[key]) for r in expected]
                if len(values) == len(set(values)):
                    return {"/": (key,)}
        if len(expected) > 1:
            raise ValueError("Informe entity_keys: gabarito com várias entidades sem identidade única")
        return {}
    if isinstance(entity_keys, str):
        entity_keys = [entity_keys]
    if isinstance(entity_keys, (tuple, list)):
        entity_keys = {"/": list(entity_keys)}
    if not isinstance(entity_keys, Mapping):
        raise ValueError("entity_keys deve ser nome, lista de nomes ou mapa caminho -> nomes")
    result = {}
    for path, fields in entity_keys.items():
        if isinstance(fields, str):
            fields = [fields]
        if not isinstance(path, str) or not path.startswith("/"):
            raise ValueError("Caminho de coleção deve começar por /")
        if not isinstance(fields, (list, tuple)) or not fields or any(not isinstance(k, str) or not k for k in fields):
            raise ValueError("Chaves de entidade devem ser nomes de campos não vazios")
        if len(fields) != len(set(fields)):
            raise ValueError("Chaves de entidade repetidas")
        result[path] = tuple(fields)
    return result


def _identity(record: dict, fields: tuple[str, ...], index: int, gold: bool) -> str:
    if any(key not in record or _is_absent(record[key]) for key in fields):
        if gold:
            raise ValueError("Gabarito contém entidade sem a identidade configurada")
        return "missing:" + str(index)
    return _json({key: json.loads(_scalar(record[key])) for key in fields})


def _facts(records: list[dict], keys: dict[str, tuple[str, ...]], gold: bool = False) -> tuple[Counter, int]:
    facts: Counter = Counter()
    duplicate_entities = 0

    def walk(value: Any, entity: str, path: str, schema_path: str) -> None:
        nonlocal duplicate_entities
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise ValueError("Nomes de campo devem ser strings")
                suffix = "/" + _pointer(key)
                walk(child, entity, path + suffix, schema_path + suffix)
        elif isinstance(value, list):
            fields = keys.get(schema_path)
            if fields:
                if any(not isinstance(item, dict) for item in value):
                    raise ValueError(f"Coleção {schema_path} com identidade exige objetos")
                identities = [_identity(item, fields, i, gold) for i, item in enumerate(value)]
                duplicates = len(identities) - len(set(identities))
                if gold and duplicates:
                    raise ValueError(f"Identidades repetidas no gabarito em {schema_path}")
                duplicate_entities += duplicates
                for item, identity in zip(value, identities):
                    walk(item, entity, path + "/@" + _pointer(identity), schema_path + "/*")
            else:
                # Sem identidade declarada, a posição faz parte do contrato da lista.
                for i, item in enumerate(value):
                    walk(item, entity, path + "/" + str(i), schema_path + "/*")
        elif not _is_absent(value):
            facts[(entity, path, _scalar(value))] += 1

    fields = keys.get("/")
    if fields:
        identities = [_identity(record, fields, i, gold) for i, record in enumerate(records)]
    elif len(records) <= 1:
        identities = ["single"] * len(records)
    else:
        # Sem chave e gold de uma entidade: registros excedentes são entidades extras.
        identities = ["single"] + [f"extra:{i}" for i in range(1, len(records))]
    duplicates = len(identities) - len(set(identities))
    if gold and duplicates:
        raise ValueError("Gabarito contém identidades repetidas")
    duplicate_entities += duplicates
    for record, identity in zip(records, identities):
        walk(record, identity, "", "")
    return facts, duplicate_entities


def _fact_list(facts: Counter) -> list[dict]:
    return [{"entity": entity, "path": path, "value": json.loads(value), "count": count}
            for (entity, path, value), count in sorted(facts.items()) if count]


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _scores(tp: int, fp: int, fn: int) -> dict:
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn),
            "f1": _ratio(2 * tp, 2 * tp + fp + fn)}


def evaluate_extraction(records: list[dict], expected: list[dict], entity_keys: Any = None) -> dict:
    """Precision/recall/F1 dos fatos, incluindo registros/campos extras e omitidos.

    ``entity_keys=['nome']`` torna o resultado independente da ordem dos registros.
    ``{'/':['id'], '/pessoas':['nome']}`` também alinha listas de entidades aninhadas.
    Listas sem chave declarada são sequências ordenadas. Duplicatas contam como FP.
    ``None`` em uma métrica significa denominador zero, nunca desempenho perfeito.
    """
    records, expected = _records(records, "records"), _records(expected, "expected")
    keys = _keys(expected, entity_keys)
    predicted, duplicates = _facts(records, keys)
    reference, _ = _facts(expected, keys, gold=True)
    correct, extra, missing = predicted & reference, predicted - reference, reference - predicted
    return {**_scores(sum(correct.values()), sum(extra.values()), sum(missing.values())),
            "predicted_facts": sum(predicted.values()), "expected_facts": sum(reference.values()),
            "duplicate_entities": duplicates, "entity_keys": {k: list(v) for k, v in keys.items()},
            "false_positive_facts": _fact_list(extra), "false_negative_facts": _fact_list(missing),
            "comparison": "typed JSON exact match; explicit gold normalization; null/abstention excluded"}


def evaluate_pair(before: list[dict], after: list[dict], expected: list[dict], entity_keys: Any = None) -> dict:
    """Avalia qualquer intervenção, sem pressupor que ela melhora os dados.

    Contagens de recuperação/perda são de fatos (não de chamadas ao reparador).
    Trocar um erro por outro conta como remoção e introdução de erro; remover um
    fato correto conta como perda mesmo quando a saída final é uma abstenção.
    """
    before, after, expected = (_records(before, "before"), _records(after, "after"), _records(expected, "expected"))
    keys = _keys(expected, entity_keys)
    reference, _ = _facts(expected, keys, gold=True)
    first, _ = _facts(before, keys)
    last, _ = _facts(after, keys)
    old_tp, new_tp = first & reference, last & reference
    old_fp, new_fp = first - reference, last - reference
    recovered, lost = new_tp - old_tp, old_tp - new_tp
    introduced, removed = new_fp - old_fp, old_fp - new_fp
    return {"before": evaluate_extraction(before, expected, keys),
            "after": evaluate_extraction(after, expected, keys),
            "repair": {"correct_facts_recovered": sum(recovered.values()),
                       "correct_facts_lost": sum(lost.values()),
                       "incorrect_facts_introduced": sum(introduced.values()),
                       "incorrect_facts_removed": sum(removed.values()),
                       "recovered": _fact_list(recovered), "lost": _fact_list(lost),
                       "introduced": _fact_list(introduced), "removed": _fact_list(removed)}}


def evaluate_detector(observed: list[dict], expected: list[dict]) -> dict:
    """Matriz multiclasse; decisões inconclusivas continuam explícitas.

    Anotações: ``{'record': 0, 'field': 'idade', 'decision': 'ATRIBUICAO_INCORRETA'}``.
    Índices aqui localizam candidatos fixos, não alinham entidades do gold factual.
    Rótulos inválidos, duplicados e IDs inconsistentes não são coagidos a bool.
    Predições sem anotação não viram falsos positivos: a precisão usa somente
    gold factual conclusivo e informa a cobertura de anotação desse denominador.
    """
    def index(rows: Any, label: str) -> dict:
        if not isinstance(rows, list):
            raise ValueError(f"{label} deve ser uma lista")
        result = {}
        for row in rows:
            if not isinstance(row, dict) or type(row.get("record")) is not int or row["record"] < 0:
                raise ValueError(f"{label}: record deve ser inteiro não negativo")
            if not isinstance(row.get("field"), str) or not row["field"]:
                raise ValueError(f"{label}: field deve ser texto não vazio")
            if row.get("decision") not in DECISOES:
                raise ValueError(f"{label}: decisão desconhecida {row.get('decision')!r}")
            key = (row["record"], row["field"])
            if key in result:
                raise ValueError(f"{label}: anotação duplicada {key}")
            result[key] = row["decision"]
        return result

    actual, gold = index(observed, "observed"), index(expected, "expected")
    matrix = {label: {decision: 0 for decision in DECISOES + ("MISSING",)} for label in DECISOES}
    mismatches = []
    binary = {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "inconclusive": 0}
    for key, label in gold.items():
        decision = actual.get(key, "MISSING")
        matrix[label][decision] += 1
        if decision != label:
            mismatches.append({"record": key[0], "field": key[1], "expected": label, "observed": decision})
        if label not in CLASSES_FACTUAIS:
            continue
        if decision not in CLASSES_FACTUAIS:
            binary["inconclusive"] += 1
            continue
        incorrect, detected = label != "SUPORTADA", decision != "SUPORTADA"
        binary["tp" if incorrect and detected else "fp" if detected else "fn" if incorrect else "tn"] += 1
    factual_total = sum(label in CLASSES_FACTUAIS for label in gold.values())
    conclusive = binary["tp"] + binary["fp"] + binary["tn"] + binary["fn"]
    expected_errors = sum(label in CLASSES_FACTUAIS[1:] for label in gold.values())
    observed_errors = sum(label in CLASSES_FACTUAIS[1:] for label in actual.values())
    annotated_error_predictions = binary["tp"] + binary["fp"]
    supported_predictions = sum(label in CLASSES_FACTUAIS and actual.get(key) == "SUPORTADA"
                                for key, label in gold.items())
    false_supports = sum(gold[key] in CLASSES_FACTUAIS[1:] and actual.get(key) == "SUPORTADA"
                         for key in gold)
    return {"confusion_matrix": matrix, "annotated": len(gold), "matched": len(set(gold) & set(actual)),
            "prediction_annotation_coverage": _ratio(len(set(gold) & set(actual)), len(actual)),
            "exact_decision_accuracy": _ratio(len(gold) - len(mismatches), len(gold)),
            "decision_counts": dict(Counter(actual.values())), "mismatches": mismatches,
            "unannotated_predictions": [{"record": k[0], "field": k[1], "decision": actual[k]}
                                        for k in actual.keys() - gold.keys()],
            "binary_conclusive_only": {**binary, **_scores(binary["tp"], binary["fp"], binary["fn"]),
                                       "coverage": _ratio(conclusive, factual_total)},
            "hallucination_detection_recall_all_annotated": _ratio(binary["tp"], expected_errors),
            "hallucination_detection_precision_on_annotated_facts": _ratio(binary["tp"], annotated_error_predictions),
            "error_predictions_with_factual_annotation": annotated_error_predictions,
            "error_predictions_total": observed_errors,
            "error_prediction_factual_annotation_coverage": _ratio(annotated_error_predictions, observed_errors),
            "false_supports": false_supports,
            "supported_predictions_on_annotated_facts": supported_predictions,
            "false_support_rate": _ratio(false_supports, supported_predictions),
            "note": "Inconclusive decisions are not correct detections; conditional metrics require coverage. "
                    "Unannotated predictions are not false positives; precision uses factual annotations only."}


def load_corpus(path: str | Path | None = None) -> dict:
    """Carrega corpus local e valida a anotação antes de executar o verificador."""
    from .contrato import ContractError, loads_json, validate_records, validate_schema

    raw = Path(path or CORPUS_PADRAO).read_bytes()
    corpus = loads_json(raw.decode("utf-8-sig"))
    if not isinstance(corpus, dict) or corpus.get("version") != 1 or corpus.get("synthetic") is not True:
        raise ValueError("Corpus exige version=1 e synthetic=true explícitos")
    if not isinstance(corpus.get("cases"), list) or not corpus["cases"]:
        raise ValueError("Corpus sem casos")
    ids = set()
    for case in corpus["cases"]:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"]:
            raise ValueError("Caso sem identificador")
        if case["id"] in ids:
            raise ValueError("ID de caso duplicado")
        ids.add(case["id"])
        if not isinstance(case.get("source"), str) or not isinstance(case.get("schema"), dict):
            raise ValueError(f"{case['id']}: fonte/schema inválidos")
        if type(case.get("expected_contract_valid", True)) is not bool:
            raise ValueError(f"{case['id']}: expected_contract_valid deve ser booleano")
        validate_schema(case["schema"])
        validate_records(case["gold"], case["schema"])
        try:
            validate_records(case["before"], case["schema"])
            valid_contract = True
        except ContractError:
            valid_contract = False
        if valid_contract != case.get("expected_contract_valid", True):
            raise ValueError(f"{case['id']}: anotação de validade contratual inconsistente")
        evaluate_extraction(case.get("before"), case.get("gold"), case.get("entity_keys"))
        evaluate_detector([], case.get("expected_decisions"))
        for evidence in case.get("gold_evidence", []):
            if not isinstance(evidence, dict) or type(evidence.get("source_offset")) is not int:
                raise ValueError(f"{case['id']}: evidência do gold inválida")
            quote, offset = evidence.get("quote"), evidence["source_offset"]
            if not isinstance(quote, str) or not quote or offset < 0 or case["source"][offset:offset + len(quote)] != quote:
                raise ValueError(f"{case['id']}: citação do gold não coincide com fonte/offset")
        if "proposed_after" in case:
            evaluate_pair(case["before"], case["proposed_after"], case["gold"], case.get("entity_keys"))
    corpus["sha256"] = hashlib.sha256(raw).hexdigest()
    return corpus


def run_benchmark(path: str | Path | None = None) -> dict:
    """Executa somente o verificador local sobre candidatos sintéticos fixos."""
    from .config import Config
    from .contrato import ContractError
    from .verificador import reparar_e_reverificar, verificar_dados

    corpus = load_corpus(path)
    outputs = []
    all_observed, all_expected = [], []
    for case in corpus["cases"]:
        output = {"id": case["id"], "tags": case.get("tags", []), "before": case["before"],
                  "extraction_before": evaluate_extraction(case["before"], case["gold"], case.get("entity_keys")),
                  "expected_contract_valid": case.get("expected_contract_valid", True)}
        for row in case["expected_decisions"]:
            all_expected.append({**row, "field": case["id"] + ":" + row["field"]})
        # Falhas de execução permanecem visíveis e não removem casos do relatório.
        try:
            config = Config(**corpus.get("config", {"data_referencia": "2026-10-05"}))
            report = verificar_dados(copy.deepcopy(case["before"]), case["source"],
                                     config=config, com_reparo=True, schema=case["schema"])
            if not output["expected_contract_valid"]:
                raise RuntimeError("Candidato inválido foi aceito pelo contrato")
            observed = [{"record": result.afirmacao.registro, "field": result.afirmacao.campo,
                         "decision": result.veredito} for result in report.afirmacoes]
            all_observed.extend({**row, "field": case["id"] + ":" + row["field"]} for row in observed)
            after, report_after, changes = reparar_e_reverificar(report, case["source"])
            output.update({"status": "completed", "contract_valid": True,
                           "detector": evaluate_detector(observed, case["expected_decisions"]),
                           "extraction_and_repair": evaluate_pair(case["before"], after, case["gold"], case.get("entity_keys")),
                           "after": after, "repair_changes": changes,
                           "observed": observed, "config": report.config.to_dict(),
                           "after_decisions": [{"record": r.afirmacao.registro, "field": r.afirmacao.campo,
                                                "decision": r.veredito} for r in report_after.afirmacoes]})
            if "proposed_after" in case:
                output["independent_intervention_example"] = evaluate_pair(
                    case["before"], case["proposed_after"], case["gold"], case.get("entity_keys"))
        except ContractError as error:
            output.update({"status": "contract_rejected" if not output["expected_contract_valid"] else "execution_error",
                           "contract_valid": False, "error_type": type(error).__name__, "error": str(error)})
        except Exception as error:
            output.update({"status": "execution_error", "error_type": type(error).__name__, "error": str(error)})
        outputs.append(output)
    totals = {"before": Counter(), "after": Counter(), "repair": Counter()}
    before_all = Counter()
    for output in outputs:
        before_all.update({key: output["extraction_before"][key] for key in ("tp", "fp", "fn")})
        if output["status"] != "completed":
            continue
        pair = output["extraction_and_repair"]
        for phase in ("before", "after"):
            totals[phase].update({key: pair[phase][key] for key in ("tp", "fp", "fn")})
        totals["repair"].update({key: value for key, value in pair["repair"].items() if isinstance(value, int)})
    detector = evaluate_detector(all_observed, all_expected)
    return {"benchmark": corpus["name"], "version": corpus["version"], "sha256": corpus["sha256"],
            "synthetic": True, "provenance": corpus.get("provenance"),
            "limitations": corpus.get("limitations", []),
            "total_cases": len(outputs), "completed_cases": sum(o["status"] == "completed" for o in outputs),
            "execution_errors": sum(o["status"] == "execution_error" for o in outputs),
            "expected_contract_rejections": sum(o["status"] == "contract_rejected" for o in outputs),
            "all_candidates_extraction_before": _scores(**before_all),
            "paired_cases": sum(o["status"] == "completed" for o in outputs),
            "micro_extraction_scope": "Only cases with completed, reverified repair; same paired cases before and after.",
            "micro_extraction": {phase: _scores(**totals[phase]) if totals[phase] else _scores(0, 0, 0)
                                 for phase in ("before", "after")},
            "repair_totals": dict(totals["repair"]),
            "detector": detector,
            "detector_confusion_matrix": detector["confusion_matrix"],
            "cases": outputs}


def format_benchmark(result: dict) -> str:
    """Resumo textual sem equiparar êxito de execução a eficácia científica."""
    lines = [f"Benchmark: {result['benchmark']} v{result['version']}",
             "Corpus sintético; não é CIL nem resultado de chamadas reais a LLM.",
             f"SHA-256: {result['sha256']}",
             f"Casos executados: {result['completed_cases']}/{result['total_cases']}; erros: {result['execution_errors']}"]
    lines.append(f"Rejeições contratuais esperadas: {result['expected_contract_rejections']}; pares antes/após: {result['paired_cases']}")
    lines.append("Antes/após abaixo inclui somente os mesmos casos concluídos e reverificados.")
    for phase, label in (("before", "Antes"), ("after", "Após reparo")):
        m = result["micro_extraction"][phase]
        lines.append(f"{label}: TP={m['tp']} FP={m['fp']} FN={m['fn']}; precisão={m['precision']} recall={m['recall']} F1={m['f1']}")
    lines.append("Reparos (contagem de fatos): " + _json(result["repair_totals"]))
    detector = result["detector"]
    lines.append(f"Detector: acurácia das decisões={detector['exact_decision_accuracy']}; "
                 f"cobertura conclusiva={detector['binary_conclusive_only']['coverage']}; "
                 f"recall de erros sobre todos os anotados={detector['hallucination_detection_recall_all_annotated']}; "
                 f"falsos suportes={detector['false_supports']}")
    lines.append(f"Precisão de erros entre fatos anotados={detector['hallucination_detection_precision_on_annotated_facts']}; "
                 f"cobertura de anotação factual das predições de erro={detector['error_prediction_factual_annotation_coverage']}")
    for case in result["cases"]:
        if case["status"] == "execution_error":
            lines.append(f"ERRO {case['id']}: {case['error_type']}: {case['error']}")
        elif case["status"] == "contract_rejected":
            lines.append(f"CONTRATO {case['id']}: rejeição esperada; {case['error']}")
        else:
            detector = case["detector"]
            lines.append(f"{case['id']}: {len(detector['mismatches'])}/{detector['annotated']} decisões divergentes; "
                         f"inconclusivas={detector['binary_conclusive_only']['inconclusive']}; "
                         f"sem anotação={len(detector['unannotated_predictions'])}")
    lines.extend("Limitação: " + limitation for limitation in result["limitations"])
    return "\n".join(lines) + "\n"
