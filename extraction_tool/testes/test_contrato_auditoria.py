"""Regressões offline: Gemini simulado, arquivos somente em TemporaryDirectory."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ic_contract import ContractError, build_schema, canonical_json

spec = importlib.util.spec_from_file_location("extraction_audit_app", ROOT / "extraction_tool/updated_app.py")
appmod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(appmod)

MODEL = appmod.GEMINI_DEFAULT_MODEL


class ExtractionAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ic_extraction_test_")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(appmod, "RESULTS_FOLDER", str(self.directory)).start()
        patch.dict(appmod.tasks, {}, clear=True).start()
        patch.dict(appmod.app.config, {"UPLOAD_FOLDER": str(self.directory / "uploads"), "TESTING": True}).start()
        # Falha fechada: testes nunca chegam a rede ou navegador real.
        patch("requests.sessions.Session.request", side_effect=AssertionError("Rede proibida no teste")).start()
        patch.object(appmod.webdriver, "Chrome", side_effect=AssertionError("Chrome real proibido")).start()
        # Chave no ambiente: o .env real nunca é lido pelos testes.
        patch.dict(os.environ, {"GEMINI_API_KEY": "DUMMY_TEST_KEY"}).start()

    def gemini(self, raw='[{"nome":"Maria"}]', finish="STOP", status=200):
        response = Mock(status_code=status)
        response.json.return_value = {
            "modelVersion": "gemini-test-resolved", "usageMetadata": {"totalTokenCount": 12},
            "candidates": [{"finishReason": finish, "content": {"parts": [{"text": raw}]}}]}
        return patch.object(appmod.requests, "post", return_value=response).start()

    def run_task(self, task_id="example", **kwargs):
        appmod.tasks[task_id] = {"status": "pending", "created_at": 1.0}
        appmod.process_task(task_id, fields=["nome"], model_provider=MODEL,
                            use_mock=True, api_key="DUMMY_TEST_KEY", **kwargs)
        return appmod.tasks[task_id], json.loads((self.directory / f"{task_id}_manifest.json").read_text())

    def test_single_field_and_fixed_request_parameters(self):
        post = self.gemini()
        audit = {}
        self.assertEqual(appmod.extract_fields_with_llm("Nome: Maria", ["nome"],
            MODEL, api_key="DUMMY_TEST_KEY", audit=audit), [{"nome": "Maria"}])
        args, kwargs = post.call_args
        self.assertEqual(args[0], appmod.GEMINI_API_URL.format(model=MODEL))
        self.assertNotIn("DUMMY_TEST_KEY", args[0])
        self.assertEqual(kwargs["headers"]["x-goog-api-key"], "DUMMY_TEST_KEY")
        self.assertEqual(kwargs["timeout"], 180)
        self.assertEqual(kwargs["json"]["generationConfig"]["maxOutputTokens"], 8192)
        self.assertNotIn("temperature", kwargs["json"]["generationConfig"])
        self.assertEqual(audit["parameters"]["temperature"], "default")
        self.assertEqual(audit["parameters"]["timeout_seconds"], 180)
        self.assertEqual(audit["parameters"]["max_retries"], 0)
        self.assertNotIn("5 PRIMEIRAS", audit["prompt_text"])

    def test_nested_top_level_object_is_rejected_without_silent_repair(self):
        self.gemini('{"nome":"Maria","telefones":[{"numero":"123"}]}')
        audit = {}
        with self.assertRaises(ContractError):
            appmod.extract_fields_with_llm("Nome: Maria", ["nome"], MODEL,
                                          api_key="DUMMY_TEST_KEY", audit=audit)
        self.assertIn('"telefones"', audit["raw_response_text"])

    def test_custom_schema_validates_nested_values_without_coercion(self):
        schema = {"type": "array", "items": {"type": "object", "properties": {
            "pessoa": {"type": "object", "properties": {"idade": {"type": ["integer", "null"]}},
                       "required": ["idade"], "additionalProperties": False}},
            "required": ["pessoa"], "additionalProperties": False}}
        post = self.gemini('[{"pessoa":{"idade":30}}]')
        self.assertEqual(appmod.extract_fields_with_llm("30", [], MODEL,
            api_key="DUMMY_TEST_KEY", schema=schema), [{"pessoa": {"idade": 30}}])
        post.return_value.json.return_value["candidates"][0]["content"]["parts"][0]["text"] = '[{"pessoa":{"idade":"30"}}]'
        with self.assertRaises(ContractError):
            appmod.extract_fields_with_llm("30", [], MODEL, api_key="DUMMY_TEST_KEY", schema=schema)

    def test_snapshot_manifest_hashes_and_raw_are_preserved(self):
        raw = '[{"nome":null}]'
        self.gemini(raw)
        task, manifest = self.run_task()
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["extracted_data"], [{"nome": None}])
        self.assertEqual(manifest["source"]["kind"], "html")
        self.assertEqual(manifest["source"]["path"], "example.html")
        self.assertEqual(manifest["provider"]["model"], "gemini-test-resolved")
        self.assertEqual(manifest["provider"]["parameters"]["temperature"], "default")
        for name in ("source", "processed_input", "prompt", "raw_response", "extraction"):
            descriptor = manifest[name]
            data = (self.directory / descriptor["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), descriptor["sha256"])
        self.assertEqual(manifest["schema_sha256"], hashlib.sha256(canonical_json(manifest["schema"]).encode()).hexdigest())
        self.assertEqual((self.directory / manifest["raw_response"]["path"]).read_text(), raw)
        self.assertNotIn("DUMMY_TEST_KEY", json.dumps(manifest))
        self.assertNotIn("DUMMY_TEST_KEY", (self.directory / manifest["prompt"]["path"]).read_text())

    def test_invalid_json_preserves_failure_audit_without_candidates(self):
        self.gemini('{invalid')
        task, manifest = self.run_task()
        self.assertEqual(task["status"], "error")
        self.assertEqual(task["result_count"], 0)
        self.assertEqual(manifest["status"], "error")
        self.assertEqual(manifest["error"]["type"], "ContractError")
        self.assertIsNone(manifest["extraction"])
        self.assertIsNotNone(manifest["raw_response"])
        self.assertFalse((self.directory / "example_data.json").exists())
        self.assertFalse((self.directory / "example_data.csv").exists())
        response = appmod.app.test_client().get("/api/download/example/json")
        self.assertEqual(response.status_code, 400)

    def test_http_error_is_not_a_candidate_and_does_not_persist_key(self):
        self.gemini(status=429)
        task, manifest = self.run_task()
        self.assertEqual(task["status"], "error")
        self.assertIn("HTTP 429", manifest["error"]["message"])
        self.assertNotIn("extracted_data", task)
        self.assertIsNone(manifest["raw_response"])
        self.assertNotIn("DUMMY_TEST_KEY", json.dumps(manifest))

    def test_empty_result_is_valid_success(self):
        self.gemini('[]')
        task, manifest = self.run_task()
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["result_count"], 0)
        self.assertEqual(json.loads((self.directory / manifest["extraction"]["path"]).read_text(encoding="utf-8-sig")), [])

    def test_gemini_truncation_with_text_is_rejected_and_audited(self):
        self.gemini(finish="MAX_TOKENS")
        task, manifest = self.run_task()
        self.assertEqual(task["status"], "error")
        self.assertEqual(manifest["provider"]["finish_reason"], "MAX_TOKENS")
        self.assertEqual((self.directory / manifest["raw_response"]["path"]).read_text(), '[{"nome":"Maria"}]')
        self.assertIsNone(manifest["extraction"])

    def test_gemini_block_without_candidate_is_rejected_and_audited(self):
        post = self.gemini()
        post.return_value.json.return_value = {"promptFeedback": {"blockReason": "SAFETY"}}
        audit = {}
        with self.assertRaises(appmod.ExtractionError):
            appmod.extract_fields_with_llm("Nome: Maria", ["nome"], MODEL,
                                           api_key="DUMMY_TEST_KEY", audit=audit)
        self.assertEqual(audit["finish_reason"], "SAFETY")
        self.assertNotIn("raw_response_text", audit)

    def test_thought_parts_are_not_candidate_text(self):
        post = self.gemini()
        post.return_value.json.return_value["candidates"][0]["content"]["parts"] = [
            {"text": "raciocínio interno", "thought": True}, {"text": '[{"nome":"Maria"}]'}]
        audit = {}
        self.assertEqual(appmod.extract_fields_with_llm("Nome: Maria", ["nome"], MODEL,
            api_key="DUMMY_TEST_KEY", audit=audit), [{"nome": "Maria"}])
        self.assertEqual(audit["raw_response_text"], '[{"nome":"Maria"}]')

    def test_export_failure_is_not_completed(self):
        self.gemini()
        patch.object(appmod, "generate_csv", return_value=False).start()
        task, manifest = self.run_task()
        self.assertEqual(task["status"], "error")
        self.assertIsNone(manifest["extraction"])
        self.assertFalse((self.directory / "example_data.json").exists())
        self.assertFalse(list(self.directory.glob("*.pending")))

    def test_two_same_named_uploads_keep_distinct_sources(self):
        patch.object(appmod.threading, "Thread").start()
        client = appmod.app.test_client()
        ids = []
        for payload in (b"first image", b"second image"):
            response = client.post("/api/scrape", data={"fields": "nome",
                "model_provider": MODEL, "page_image": (io.BytesIO(payload), "page.png")})
            self.assertEqual(response.status_code, 202)
            ids.append(response.json["task_id"])
        paths = [Path(appmod.tasks[task_id]["image_path"]) for task_id in ids]
        self.assertNotEqual(paths[0], paths[1])
        self.assertEqual([path.read_bytes() for path in paths], [b"first image", b"second image"])

    def test_image_is_copied_and_manifest_has_no_fake_text(self):
        self.gemini()
        original = self.directory / "upload.png"
        original.write_bytes(b"test image bytes")
        task, manifest = self.run_task(image_path=str(original))
        self.assertEqual(task["status"], "completed")
        self.assertEqual(manifest["source"]["kind"], "image")
        self.assertIsNone(manifest["processed_input"])
        snapshot = self.directory / manifest["source"]["path"]
        original.write_bytes(b"changed upload")
        self.assertEqual(snapshot.read_bytes(), b"test image bytes")

    def test_unsupported_image_format_rejected_before_api_or_thread(self):
        thread = patch.object(appmod.threading, "Thread").start()
        response = appmod.app.test_client().post("/api/scrape", data={"fields": "nome",
            "model_provider": MODEL, "page_image": (io.BytesIO(b"image"), "page.bmp")})
        self.assertEqual(response.status_code, 400)
        thread.assert_not_called()
        self.assertFalse((self.directory / "uploads").exists())

    def test_schema_only_request_and_invalid_schema_rejection(self):
        thread = patch.object(appmod.threading, "Thread").start()
        client = appmod.app.test_client()
        response = client.post("/api/scrape", data={"schema_json": json.dumps(build_schema(["nome"])),
                                                    "use_mock": "true"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(appmod.tasks[response.json["task_id"]]["fields"], ["nome"])
        thread.reset_mock()
        response = client.post("/api/scrape", data={"schema_json": '{"type":"object"}', "use_mock": "true"})
        self.assertEqual(response.status_code, 400)
        thread.assert_not_called()

    def test_driver_is_closed_after_navigation_error(self):
        driver = Mock()
        driver.get.side_effect = RuntimeError("navigation failed")
        patch.object(appmod.webdriver, "Chrome", return_value=driver).start()
        self.assertIsNone(appmod.scrape_webpage_with_selenium("https://example.invalid"))
        driver.quit.assert_called_once()

    def test_driver_quit_failure_keeps_acquired_snapshot(self):
        driver = Mock(page_source="<main>Maria</main>")
        driver.quit.side_effect = RuntimeError("quit failed")
        patch.object(appmod.webdriver, "Chrome", return_value=driver).start()
        self.assertEqual(appmod.scrape_webpage_with_selenium("https://example.invalid", wait_time=0),
                         "<main>Maria</main>")

    def test_duplicate_schema_keys_rejected_before_starting_task(self):
        thread = patch.object(appmod.threading, "Thread").start()
        duplicate = json.dumps(build_schema(["nome"])).replace('"type": "array"',
                    '"type": "object", "type": "array"', 1)
        response = appmod.app.test_client().post("/api/scrape", data={
            "schema_json": duplicate, "use_mock": "true"})
        self.assertEqual(response.status_code, 400)
        thread.assert_not_called()

    def test_unknown_and_legacy_providers_rejected_before_starting_task(self):
        thread = patch.object(appmod.threading, "Thread").start()
        for provider in ("unknown", "openai", "openai-vision", "gpt-4o-mini"):
            with self.subTest(provider=provider):
                response = appmod.app.test_client().post("/api/scrape", data={
                    "fields": "nome", "model_provider": provider, "use_mock": "true"})
                self.assertEqual(response.status_code, 400)
        thread.assert_not_called()

    def test_cleaning_error_preserves_source_and_requested_provider(self):
        patch.object(appmod, "clean_text", side_effect=RuntimeError("clean failed")).start()
        task, manifest = self.run_task()
        self.assertEqual(task["status"], "error")
        self.assertIsNotNone(manifest["source"])
        self.assertIsNone(manifest["processed_input"])
        self.assertIsNone(manifest["raw_response"])
        self.assertEqual(manifest["provider"]["name"], "gemini")
        self.assertEqual(manifest["provider"]["requested_model"], MODEL)
        self.assertIsNone(manifest["provider"]["model"])
        response = appmod.app.test_client().get("/api/status/example")
        self.assertEqual(set(response.json["artifacts"]), {"manifest", "source"})
        downloaded = appmod.app.test_client().get("/api/download/example/source")
        self.assertEqual(downloaded.status_code, 200)
        downloaded.close()

    def test_api_timeout_is_failure_with_snapshot_and_prompt(self):
        patch.object(appmod.requests, "post", side_effect=appmod.requests.Timeout("secret")).start()
        task, manifest = self.run_task()
        self.assertEqual(task["status"], "error")
        self.assertIsNotNone(manifest["source"])
        self.assertIsNotNone(manifest["prompt"])
        self.assertIsNone(manifest["raw_response"])
        self.assertNotIn("secret", json.dumps(manifest))

    def test_gemini_image_receives_preserved_bytes(self):
        post = self.gemini()
        image = self.directory / "original.png"
        image.write_bytes(b"image bytes")
        appmod.tasks["vision"] = {"status": "pending", "created_at": 1.0}
        appmod.process_task("vision", fields=["nome"], model_provider=MODEL,
                            image_path=str(image), api_key="DUMMY_TEST_KEY")
        self.assertEqual(appmod.tasks["vision"]["status"], "completed")
        parts = post.call_args.kwargs["json"]["contents"][0]["parts"]
        self.assertEqual(parts[1], {"inline_data": {"mime_type": "image/png",
                                                    "data": "aW1hZ2UgYnl0ZXM="}})

    def test_connection_error_does_not_expose_key(self):
        patch.object(appmod.requests, "post", side_effect=appmod.requests.ConnectionError(
            "Max retries exceeded with url: /v1beta/models/gemini:generateContent")).start()
        with self.assertLogs(appmod.logger, level="ERROR") as captured:
            response = appmod.app.test_client().post("/api/test-llm", data={"model_provider": MODEL})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("DUMMY_TEST_KEY", response.get_data(as_text=True))
        self.assertNotIn("DUMMY_TEST_KEY", " ".join(captured.output))


if __name__ == "__main__":
    unittest.main()
