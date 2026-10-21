"""Regressões do protocolo científico, sem produzir gold pelo verificador."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neurosimbolico.avaliacao import (
    evaluate_detector, evaluate_extraction, evaluate_pair, format_benchmark,
    load_corpus, run_benchmark,
)


class ExtractionMetricsTests(unittest.TestCase):
    def setUp(self):
        self.gold = [{"nome": "Maria", "idade": 30}, {"nome": "João", "idade": 45}]

    def test_reordered_entities_are_not_errors(self):
        scores = evaluate_extraction(list(reversed(self.gold)), self.gold, ["nome"])
        self.assertEqual((scores["tp"], scores["fp"], scores["fn"]), (4, 0, 0))

    def test_omitted_record_and_field_are_false_negatives(self):
        scores = evaluate_extraction([{"nome": "Maria"}], self.gold, ["nome"])
        self.assertEqual((scores["tp"], scores["fp"], scores["fn"]), (1, 0, 3))
        self.assertEqual(scores["recall"], .25)

    def test_wrong_attribute_creates_fp_and_fn(self):
        scores = evaluate_extraction([{"nome": "Maria", "idade": 45}], self.gold[:1], ["nome"])
        self.assertEqual((scores["tp"], scores["fp"], scores["fn"]), (1, 1, 1))

    def test_duplicate_records_are_counted(self):
        scores = evaluate_extraction(self.gold + self.gold[:1], self.gold, ["nome"])
        self.assertEqual((scores["tp"], scores["fp"], scores["duplicate_entities"]), (4, 2, 1))

    def test_nested_identities_survive_reordering(self):
        gold = [{"id": "group", "pessoas": self.gold}]
        candidate = [{"id": "group", "pessoas": list(reversed(self.gold))}]
        scores = evaluate_extraction(candidate, gold, {"/": ["id"], "/pessoas": ["nome"]})
        self.assertEqual((scores["tp"], scores["fp"], scores["fn"]), (5, 0, 0))

    def test_unkeyed_arrays_are_ordered(self):
        scores = evaluate_extraction([{"dados": [2, 1]}], [{"dados": [1, 2]}])
        self.assertEqual((scores["tp"], scores["fp"], scores["fn"]), (0, 2, 2))

    def test_scalar_types_are_not_coerced(self):
        for expected, received in ((1, "1"), (True, 1), (1, 1.0), (False, 0)):
            with self.subTest(expected=expected, received=received):
                scores = evaluate_extraction([{"value": received}], [{"value": expected}])
                self.assertEqual((scores["tp"], scores["fp"], scores["fn"]), (0, 1, 1))

    def test_zero_and_false_are_facts_but_abstentions_are_not(self):
        record = {"count": 0, "flag": False, "missing": None, "legacy": "Não disponível"}
        scores = evaluate_extraction([record], [record])
        self.assertEqual(scores["tp"], 2)

    def test_no_denominator_does_not_mean_perfect(self):
        scores = evaluate_extraction([], [])
        self.assertIsNone(scores["precision"])
        self.assertIsNone(scores["recall"])
        self.assertIsNone(scores["f1"])

    def test_extra_entity_is_false_positive(self):
        scores = evaluate_extraction(self.gold + [{"nome": "Pedro", "idade": 50}], self.gold, "nome")
        self.assertEqual((scores["tp"], scores["fp"], scores["fn"]), (4, 2, 0))

    def test_duplicate_gold_is_invalid(self):
        with self.assertRaises(ValueError):
            evaluate_extraction([], self.gold + self.gold[:1], "nome")

    def test_multiple_anonymous_entities_require_identity(self):
        with self.assertRaises(ValueError):
            evaluate_extraction([], [{"idade": 30}, {"idade": 45}])

    def test_malformed_records_and_nonfinite_numbers_fail(self):
        for records in (None, {}, ["value"], [{"number": float("nan")}], [{1: "value"}]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                evaluate_extraction(records, [])

    def test_missing_identity_cannot_match_gold(self):
        scores = evaluate_extraction([{"idade": 30}], self.gold[:1], "nome")
        self.assertEqual((scores["tp"], scores["fp"], scores["fn"]), (0, 1, 2))


class RepairMetricsTests(unittest.TestCase):
    def test_harmful_repair_is_measured(self):
        gold = [{"nome": "Maria", "idade": 30}]
        candidate = [{"nome": "Maria", "idade": 45}]
        pair = evaluate_pair(gold, candidate, gold, "nome")
        self.assertEqual(pair["repair"]["correct_facts_lost"], 1)
        self.assertEqual(pair["repair"]["incorrect_facts_introduced"], 1)
        self.assertEqual(pair["repair"]["correct_facts_recovered"], 0)

    def test_abstention_removes_error_but_does_not_recover_truth(self):
        pair = evaluate_pair([{"value": 45}], [{"value": None}], [{"value": 30}])
        self.assertEqual(pair["repair"]["incorrect_facts_removed"], 1)
        self.assertEqual(pair["repair"]["correct_facts_recovered"], 0)
        self.assertEqual(pair["after"]["fn"], 1)

    def test_wrong_to_wrong_counts_both_removed_and_introduced(self):
        pair = evaluate_pair([{"value": 45}], [{"value": 60}], [{"value": 30}])
        self.assertEqual(pair["repair"]["incorrect_facts_removed"], 1)
        self.assertEqual(pair["repair"]["incorrect_facts_introduced"], 1)

    def test_inputs_remain_unchanged(self):
        before, after, gold = [{"people": [{"nome": "Maria", "idade": 45}]}], [], []
        original = copy.deepcopy(before)
        evaluate_pair(before, after, gold)
        self.assertEqual(before, original)


class DetectorMetricsTests(unittest.TestCase):
    def test_partial_is_not_a_correct_error_detection(self):
        gold = [{"record": 0, "field": "a", "decision": "NAO_SUPORTADA"},
                {"record": 0, "field": "b", "decision": "NAO_SUPORTADA"}]
        actual = [{"record": 0, "field": "a", "decision": "NAO_SUPORTADA"},
                  {"record": 0, "field": "b", "decision": "PARCIAL"}]
        scores = evaluate_detector(actual, gold)
        self.assertEqual(scores["binary_conclusive_only"]["recall"], 1)
        self.assertEqual(scores["binary_conclusive_only"]["coverage"], .5)
        self.assertEqual(scores["hallucination_detection_recall_all_annotated"], .5)

    def test_absent_prediction_is_explicit(self):
        scores = evaluate_detector([], [{"record": 0, "field": "a", "decision": "SUPORTADA"}])
        self.assertEqual(scores["confusion_matrix"]["SUPORTADA"]["MISSING"], 1)
        self.assertEqual(scores["exact_decision_accuracy"], 0)

    def test_false_support_is_separate_from_inconclusive(self):
        actual = [{"record": 0, "field": "a", "decision": "SUPORTADA"}]
        gold = [{"record": 0, "field": "a", "decision": "ATRIBUICAO_INCORRETA"}]
        scores = evaluate_detector(actual, gold)
        self.assertEqual(scores["false_supports"], 1)
        self.assertEqual(scores["false_support_rate"], 1)

    def test_unannotated_predictions_do_not_disappear(self):
        scores = evaluate_detector([{"record": 0, "field": "a", "decision": "NAO_SUPORTADA"}], [])
        self.assertEqual(len(scores["unannotated_predictions"]), 1)
        self.assertIsNone(scores["hallucination_detection_precision_on_annotated_facts"])
        self.assertEqual(scores["error_prediction_factual_annotation_coverage"], 0)
        self.assertEqual(scores["prediction_annotation_coverage"], 0)
        self.assertEqual(scores["binary_conclusive_only"]["fp"], 0)

    def test_unannotated_error_prediction_does_not_reduce_measured_precision(self):
        actual = [{"record": 0, "field": "known_error", "decision": "NAO_SUPORTADA"},
                  {"record": 0, "field": "unknown", "decision": "NAO_SUPORTADA"}]
        gold = [{"record": 0, "field": "known_error", "decision": "NAO_SUPORTADA"}]
        scores = evaluate_detector(actual, gold)
        self.assertEqual(scores["hallucination_detection_precision_on_annotated_facts"], 1)
        self.assertEqual(scores["error_predictions_with_factual_annotation"], 1)
        self.assertEqual(scores["error_predictions_total"], 2)
        self.assertEqual(scores["error_prediction_factual_annotation_coverage"], .5)
        self.assertEqual(scores["prediction_annotation_coverage"], .5)
        self.assertEqual(scores["binary_conclusive_only"]["fp"], 0)

    def test_annotated_false_positive_reduces_precision_but_unknown_does_not(self):
        actual = [{"record": 0, "field": name, "decision": "NAO_SUPORTADA"}
                  for name in ("error", "correct", "unknown")]
        gold = [{"record": 0, "field": "error", "decision": "NAO_SUPORTADA"},
                {"record": 0, "field": "correct", "decision": "SUPORTADA"}]
        scores = evaluate_detector(actual, gold)
        self.assertEqual(scores["hallucination_detection_precision_on_annotated_facts"], .5)
        self.assertEqual(scores["error_prediction_factual_annotation_coverage"], .666667)
        self.assertEqual(scores["binary_conclusive_only"]["fp"], 1)

    def test_nonfactual_annotation_does_not_become_factual_false_positive(self):
        actual = [{"record": 0, "field": "a", "decision": "NAO_SUPORTADA"}]
        gold = [{"record": 0, "field": "a", "decision": "PARCIAL"}]
        scores = evaluate_detector(actual, gold)
        self.assertIsNone(scores["hallucination_detection_precision_on_annotated_facts"])
        self.assertEqual(scores["prediction_annotation_coverage"], 1)
        self.assertEqual(scores["error_prediction_factual_annotation_coverage"], 0)
        self.assertEqual(scores["confusion_matrix"]["PARCIAL"]["NAO_SUPORTADA"], 1)

    def test_invalid_labels_duplicate_keys_and_bool_indices_are_rejected(self):
        valid = {"record": 0, "field": "idade", "decision": "SUPORTADA"}
        for rows in ([{**valid, "decision": "false"}], [valid, valid], [{**valid, "record": True}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                evaluate_detector(rows, [])


class BenchmarkProtocolTests(unittest.TestCase):
    def _save(self, directory, corpus):
        path = Path(directory) / "corpus.json"
        path.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
        return path

    def test_eight_required_scenarios_and_adversaries_are_versioned(self):
        corpus = load_corpus()
        tags = {tag for case in corpus["cases"] for tag in case["tags"]}
        self.assertTrue({f"required_{i}" for i in range(1, 9)} <= tags)
        self.assertTrue({"negation", "currency", "duplicate_over_five", "nested", "omission", "token_boundary"} <= tags)
        self.assertEqual(corpus["config"]["data_referencia"], "2026-10-05")
        self.assertEqual(len(corpus["sha256"]), 64)

    def test_modified_gold_quote_is_rejected(self):
        corpus = load_corpus()
        corpus["cases"][0]["gold_evidence"][0]["source_offset"] += 1
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            load_corpus(self._save(directory, corpus))

    def test_mislabelled_contract_case_is_rejected(self):
        corpus = load_corpus()
        corpus["cases"][0]["expected_contract_valid"] = False
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            load_corpus(self._save(directory, corpus))

    def test_actual_verifier_and_reverified_repairs_run_offline(self):
        result = run_benchmark()
        self.assertEqual(result["total_cases"], 23)
        self.assertEqual(result["execution_errors"], 0, [c for c in result["cases"] if c["status"] == "execution_error"])
        self.assertEqual(result["expected_contract_rejections"], 2)
        self.assertEqual(result["paired_cases"], 21)
        for case in result["cases"]:
            if case["status"] == "completed":
                self.assertIn("after_decisions", case)
                self.assertIn("repair_changes", case)
                self.assertEqual(case["config"]["data_referencia"], "2026-10-05")
        self.assertGreater(result["all_candidates_extraction_before"]["fn"], result["micro_extraction"]["before"]["fn"])
        harmful = next(c for c in result["cases"] if c["id"] == "18_harmful_intervention")
        self.assertEqual(harmful["independent_intervention_example"]["repair"]["correct_facts_lost"], 1)
        self.assertIn("Corpus sintético", format_benchmark(result))

    def test_operational_failures_stay_in_denominators_and_report(self):
        with patch("neurosimbolico.verificador.verificar_dados", side_effect=RuntimeError("injected failure")):
            result = run_benchmark()
        self.assertEqual(result["execution_errors"], 23)
        self.assertEqual(result["paired_cases"], 0)
        self.assertGreater(result["all_candidates_extraction_before"]["fn"], 0)
        self.assertIsNone(result["micro_extraction"]["after"]["recall"])
        self.assertEqual(result["detector"]["exact_decision_accuracy"], 0)
        self.assertEqual(result["detector"]["binary_conclusive_only"]["coverage"], 0)


if __name__ == "__main__":
    unittest.main()
