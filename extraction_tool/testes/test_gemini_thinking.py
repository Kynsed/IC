"""Verificações offline do modelo Gemini e Thinking Level selecionados."""
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location(
    "gemini_thinking_app", ROOT / "extraction_tool/updated_app.py")
appmod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(appmod)

LEVELS = {
    "gemini-3.8-flash": ("default", "low", "medium", "high"),
    "gemini-3.7-flash": ("default", "low", "medium", "high"),
    "gemini-3.6-flash": ("default", "minimal", "low", "medium", "high"),
}
COMBINATIONS = [(model, level) for model, levels in LEVELS.items() for level in levels]


class GeminiThinkingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ic_gemini_thinking_")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(appmod, "RESULTS_FOLDER", str(self.directory)).start()
        patch.dict(appmod.tasks, {}, clear=True).start()
        patch.dict(appmod.app.config, {
            "UPLOAD_FOLDER": str(self.directory / "uploads"), "TESTING": True}).start()
        patch("requests.sessions.Session.request",
              side_effect=AssertionError("Rede real proibida neste teste")).start()
        patch.object(appmod.webdriver, "Chrome",
                     side_effect=AssertionError("Navegador real proibido neste teste")).start()
        self.client = appmod.app.test_client()

    def response(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "candidates": [{"finishReason": "STOP", "content": {
                "parts": [{"text": '[{"nome":"Maria"}]'}]}}]}
        return patch.object(appmod.requests, "post", return_value=response).start()

    def assert_generation_config(self, post, model, level, max_tokens=8192):
        args, kwargs = post.call_args
        self.assertEqual(args[0], appmod.GEMINI_API_URL.format(model=model))
        expected = {"maxOutputTokens": max_tokens}
        if level != "default":
            expected["thinkingConfig"] = {"thinkingLevel": level}
        self.assertEqual(kwargs["json"]["generationConfig"], expected)

    def test_central_compatibility_and_model_default(self):
        self.assertEqual(set(appmod.GEMINI_SUPPORTED_MODELS), set(LEVELS))
        self.assertEqual(appmod.GEMINI_DEFAULT_MODEL, "gemini-3.8-flash")
        self.assertEqual(appmod.GEMINI_THINKING_LEVELS,
                         {model: set(levels) - {"default"} for model, levels in LEVELS.items()})
        for model, level in COMBINATIONS:
            with self.subTest(model=model, level=level):
                self.assertEqual(appmod.validate_gemini_thinking_level(model, level), level)

    def test_all_13_payloads_and_audit_parameters(self):
        post = self.response()
        for model, level in COMBINATIONS:
            with self.subTest(model=model, level=level):
                audit = {}
                self.assertEqual(appmod.call_gemini_api(
                    "Fonte", model, api_key="TEST_KEY", max_tokens=1234,
                    audit=audit, thinking_level=level), '[{"nome":"Maria"}]')
                self.assert_generation_config(post, model, level, 1234)
                self.assertEqual(audit["parameters"]["thinking_level"], level)
                self.assertEqual(audit["parameters"]["max_output_tokens"], 1234)
                self.assertEqual(audit["requested_model"], model)
        self.assertEqual(post.call_count, 13)

    def test_omitted_parameter_defaults_to_no_thinking_config(self):
        post = self.response()
        for name in ("call_gemini_api", "extract_fields_with_llm", "process_url", "process_task"):
            self.assertEqual(inspect.signature(getattr(appmod, name)).parameters[
                "thinking_level"].default, "default")
        audit = {}
        appmod.call_gemini_api("Fonte", "gemini-3.8-flash", api_key="TEST_KEY", audit=audit)
        self.assert_generation_config(post, "gemini-3.8-flash", "default")
        self.assertEqual(audit["parameters"]["thinking_level"], "default")

    def test_invalid_levels_are_rejected_before_api_request(self):
        post = self.response()
        for model, level in (("gemini-3.8-flash", "minimal"),
                             ("gemini-3.7-flash", "minimal"),
                             ("gemini-3.6-flash", "unknown"),
                             ("gemini-3.8-flash", ""),
                             ("gemini-3.8-flash", "LOW")):
            with self.subTest(model=model, level=level), self.assertRaisesRegex(
                    ValueError, "Thinking level") as error:
                appmod.call_gemini_api("Fonte", model, api_key="TEST_KEY", thinking_level=level)
            self.assertIn(model, str(error.exception))
            self.assertIn(repr(level), str(error.exception))
        with self.assertRaises(appmod.ExtractionError):
            appmod.call_gemini_api("Fonte", "gemini-2.0-flash", api_key="TEST_KEY")
        post.assert_not_called()

    def test_scrape_receives_and_forwards_all_combinations(self):
        thread = patch.object(appmod.threading, "Thread").start()
        for model, level in COMBINATIONS:
            with self.subTest(model=model, level=level):
                response = self.client.post("/api/scrape", data={
                    "fields": "nome", "use_mock": "true", "model_provider": model,
                    "thinking_level": level, "api_key": "TEST_KEY"})
                self.assertEqual(response.status_code, 202, response.json)
                kwargs = thread.call_args.kwargs
                self.assertIs(kwargs["target"], appmod.process_task)
                bound = inspect.signature(appmod.process_task).bind(
                    *kwargs.get("args", ()), **kwargs.get("kwargs", {}))
                bound.apply_defaults()
                self.assertEqual(bound.arguments["model_provider"], model)
                self.assertEqual(bound.arguments["thinking_level"], level)
                self.assertEqual(bound.arguments["api_key"], "TEST_KEY")
        self.assertEqual(thread.return_value.start.call_count, 13)

    def test_connection_receives_exact_model_and_level_get_and_post(self):
        post = self.response()
        for method in ("get", "post"):
            for model, level in COMBINATIONS:
                with self.subTest(method=method, model=model, level=level):
                    data = {"model_provider": model, "thinking_level": level, "api_key": "TEST_KEY"}
                    response = getattr(self.client, method)("/api/test-llm", **{
                        "query_string" if method == "get" else "data": data})
                    self.assertEqual(response.status_code, 200, response.json)
                    self.assert_generation_config(post, model, level, 2048)
        self.assertEqual(post.call_count, 26)

    def test_both_endpoints_default_when_level_is_omitted(self):
        post = self.response()
        response = self.client.post("/api/test-llm", data={"api_key": "TEST_KEY"})
        self.assertEqual(response.status_code, 200, response.json)
        self.assert_generation_config(post, "gemini-3.8-flash", "default", 2048)
        thread = patch.object(appmod.threading, "Thread").start()
        response = self.client.post("/api/scrape", data={"fields": "nome", "use_mock": "true"})
        self.assertEqual(response.status_code, 202, response.json)
        call = thread.call_args.kwargs
        bound = inspect.signature(appmod.process_task).bind(*call.get("args", ()), **call.get("kwargs", {}))
        bound.apply_defaults()
        self.assertEqual(bound.arguments["model_provider"], "gemini-3.8-flash")
        self.assertEqual(bound.arguments["thinking_level"], "default")

    def test_invalid_combinations_return_400_without_starting_work(self):
        thread = patch.object(appmod.threading, "Thread").start()
        post = self.response()
        for endpoint in ("/api/scrape", "/api/test-llm"):
            for model, level in (("gemini-3.8-flash", "minimal"),
                                 ("gemini-3.7-flash", "minimal"),
                                 ("gemini-3.6-flash", "unknown"),
                                 ("gemini-3.8-flash", ""),
                                 ("gemini-2.0-flash", "default")):
                with self.subTest(endpoint=endpoint, model=model, level=level):
                    response = self.client.post(endpoint, data={"fields": "nome", "use_mock": "true",
                        "model_provider": model, "thinking_level": level, "api_key": "TEST_KEY"})
                    self.assertEqual(response.status_code, 400, response.json)
                    self.assertTrue(response.json.get("error") or response.json.get("message"))
                    if model in LEVELS:
                        self.assertIn(repr(level), json.dumps(response.json))
                        self.assertIn(model, json.dumps(response.json))
        thread.assert_not_called()
        post.assert_not_called()
        self.assertFalse(appmod.tasks)

    def test_task_propagation_and_manifest_for_all_combinations(self):
        post = self.response()
        for index, (model, level) in enumerate(COMBINATIONS):
            with self.subTest(model=model, level=level):
                task_id = f"thinking-{index}"
                appmod.tasks[task_id] = {"status": "pending", "created_at": 1.0}
                appmod.process_task(task_id, fields=["nome"], model_provider=model,
                                    use_mock=True, api_key="TEST_KEY", thinking_level=level)
                self.assertEqual(appmod.tasks[task_id]["status"], "completed", appmod.tasks[task_id])
                self.assert_generation_config(post, model, level)
                manifest = json.loads((self.directory / f"{task_id}_manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["provider"]["parameters"]["thinking_level"], level)
                self.assertEqual(manifest["provider"]["requested_model"], model)

    def test_early_failure_keeps_selected_level_in_manifest(self):
        patch.object(appmod, "process_url", side_effect=appmod.ExtractionError("Falha simulada")).start()
        for level in ("default", "high"):
            task_id = f"early-{level}"
            appmod.tasks[task_id] = {"status": "pending", "created_at": 1.0}
            appmod.process_task(task_id, fields=["nome"], use_mock=True, thinking_level=level)
            manifest = json.loads((self.directory / f"{task_id}_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "error")
            self.assertEqual(manifest["provider"]["parameters"]["thinking_level"], level)

    def test_image_path_propagates_level_without_changing_image_request(self):
        post = self.response()
        image = self.directory / "source.png"
        image.write_bytes(b"offline-image-fixture")
        for level in ("default", "minimal"):
            data, text, count = appmod.process_url(None, ["nome"], "gemini-3.6-flash",
                image_path=str(image), api_key="TEST_KEY", thinking_level=level)
            self.assertEqual((data, text, count), ([{"nome": "Maria"}], None, 1))
            self.assert_generation_config(post, "gemini-3.6-flash", level)
            image_part = post.call_args.kwargs["json"]["contents"][0]["parts"][1]
            self.assertEqual(image_part["inline_data"]["mime_type"], "image/png")


if __name__ == "__main__":
    unittest.main()
