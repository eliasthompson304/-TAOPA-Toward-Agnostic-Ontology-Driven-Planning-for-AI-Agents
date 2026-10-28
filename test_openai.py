"""Offline API tests. Every request uses a fake key and an HTTP mock."""

# Local regression checks, not a reproduction of any paper's experiments.
# Mock outputs verify program contracts; ontology accuracy, correction effort,
# and downstream reliability require separate evaluation (REPORT.md, section 10).

from contextlib import redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI

import openai_client
import prototype


def response(text='{"classes": []}', status="completed"):
    return {
        "id": "resp_test", "object": "response", "created_at": 0,
        "model": openai_client.GENERATION_MODEL, "status": status,
        "output": [{"id": "msg_test", "type": "message", "role": "assistant",
                    "status": "completed", "content": [
                        {"type": "output_text", "text": text, "annotations": []}]}],
    }


class OpenAITests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.status = 200
        self.body = response()
        self.error = None
        connection = patch("openai_client.connect", side_effect=self.client)
        connection.start()
        self.addCleanup(connection.stop)

    def client(self, timeout):
        return OpenAI(api_key="test-api-key", timeout=timeout, max_retries=0,
                      http_client=httpx.Client(transport=httpx.MockTransport(self.handle)))

    def handle(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return httpx.Response(self.status, json=self.body)

    def test_generation_uses_responses_json_mode_without_storage(self):
        messages = [{"role": "system", "content": "Return a JSON object."}]
        self.assertEqual(openai_client.ask_json(messages), {"classes": []})
        request = self.requests[0]
        self.assertEqual(str(request.url), "https://api.openai.com/v1/responses")
        self.assertEqual(request.headers["authorization"], "Bearer test-api-key")
        body = json.loads(request.content)
        self.assertEqual(body["input"], messages)
        self.assertEqual(body["model"], openai_client.GENERATION_MODEL)
        self.assertEqual(body["text"], {"format": {"type": "json_object"}})
        self.assertEqual(body["max_output_tokens"], 4096)
        self.assertFalse(body["store"])
        self.assertEqual(body["reasoning"], {"effort": "none"})
        self.assertNotIn("test-api-key", request.content.decode())

    def test_model_can_be_selected_explicitly(self):
        openai_client.ask_json([], model="selected-model")
        body = json.loads(self.requests[0].content)
        self.assertEqual(body["model"], "selected-model")
        self.assertNotIn("reasoning", body)

    def test_failed_response_is_a_sanitized_service_error(self):
        self.body = response(status="failed")
        self.body["error"] = {"code": "server_error", "message": "Sensitive test-api-key"}
        with self.assertRaises(openai_client.ModelError) as caught:
            openai_client.ask_json([])
        self.assertNotIsInstance(caught.exception, openai_client.ModelOutputError)
        self.assertNotIn("test-api-key", str(caught.exception))

    def test_malformed_or_incomplete_generation_keeps_raw_reply(self):
        for text, status in [("not JSON", "completed"), ("[]", "completed"),
                             ('{"classes": []}', "incomplete")]:
            with self.subTest(text=text, status=status):
                self.body = response(text, status)
                with self.assertRaises(openai_client.ModelOutputError) as caught:
                    openai_client.ask_json([])
                self.assertEqual(caught.exception.response["status"], status)
                self.assertNotIn("test-api-key", json.dumps(caught.exception.response))

    def test_refusal_is_a_rejected_model_output(self):
        self.body["output"][0]["content"] = [{"type": "refusal", "refusal": "Declined"}]
        with self.assertRaisesRegex(openai_client.ModelOutputError, "declined"):
            openai_client.ask_json([])

    def test_embeddings_are_sorted_by_input_index(self):
        self.body = {"object": "list", "model": openai_client.EMBEDDING_MODEL,
                     "data": [{"object": "embedding", "index": 1, "embedding": [3, 4]},
                              {"object": "embedding", "index": 0, "embedding": [1, 2]}],
                     "usage": {"prompt_tokens": 2, "total_tokens": 2}}
        self.assertEqual(openai_client.embed(["first", "second"]), [[1, 2], [3, 4]])
        request = self.requests[0]
        self.assertEqual(request.url.path, "/v1/embeddings")
        self.assertEqual(json.loads(request.content), {
            "model": openai_client.EMBEDDING_MODEL, "input": ["first", "second"],
            "encoding_format": "float"})

    def test_bad_embedding_indexes_or_values_stop_processing(self):
        for indexes, values in [([0, 0], [[1], [2]]), ([1], [[1]]),
                                ([0], [[0, 0]]), ([0], [[]])]:
            with self.subTest(indexes=indexes, values=values):
                self.body = {"data": [{"object": "embedding", "index": index, "embedding": vector}
                                      for index, vector in zip(indexes, values)]}
                with self.assertRaises(openai_client.ModelError):
                    openai_client.embed(["first"] * len(values))

    def test_empty_embeddings_do_not_make_requests(self):
        self.assertEqual(openai_client.embed([]), [])
        self.assertEqual(self.requests, [])

    def test_vector_validation_and_cosine(self):
        for values in [[[0, 0]], [[float("nan")]], [[True]], [[1], [1, 2]], []]:
            with self.subTest(values=values), self.assertRaises(openai_client.ModelError):
                openai_client.check_vectors(values, 1)
        with self.assertRaises(openai_client.ModelError):
            openai_client.cosine([1, 2], [1])
        self.assertAlmostEqual(openai_client.cosine([1, 0], [1, 0]), 1)

    def test_http_errors_do_not_expose_error_bodies_or_retry(self):
        self.body = {"error": {"message": "Sensitive test-api-key", "type": "invalid_request_error"}}
        for status in [400, 401, 404, 429, 500]:
            for call, argument in [(openai_client.ask_json, []), (openai_client.embed, ["text"])]:
                with self.subTest(status=status, call=call.__name__):
                    self.status = status
                    count = len(self.requests)
                    with self.assertRaises(openai_client.ModelError) as caught:
                        call(argument)
                    self.assertIn(str(status), str(caught.exception))
                    self.assertNotIn("test-api-key", str(caught.exception))
                    self.assertEqual(len(self.requests), count + 1)
                    self.assertTrue(caught.exception.__suppress_context__)

    def test_connection_failures_are_sanitized_service_errors(self):
        for error in [httpx.ConnectError("Sensitive test-api-key"), httpx.ReadTimeout("timeout")]:
            with self.subTest(error=type(error).__name__):
                self.error = error
                with self.assertRaises(openai_client.ModelError) as caught:
                    openai_client.ask_json([])
                self.assertNotIsInstance(caught.exception, openai_client.ModelOutputError)
                self.assertNotIn("test-api-key", str(caught.exception))

    def test_429_distinguishes_quota_spend_and_rate_limits_without_leaking_messages(self):
        self.status = 429
        cases = [
            ("insufficient_quota", "insufficient_quota", "API quota exhausted"),
            ("credit_balance_exhausted", "insufficient_quota", "API credits exhausted"),
            ("organization_spend_limit_exceeded", "insufficient_quota", "Organization spend limit"),
            ("project_spend_limit_exceeded", "insufficient_quota", "Project spend limit"),
            ("organization_usage_limit_exceeded", "insufficient_quota", "Organization usage limit"),
            ("rate_limit_exceeded", "requests", "Temporary rate limit"),
            ("slow_down", "rate_limit_error", "Request rate increased"),
            (None, "rate_limit_error", "Temporary rate limit"),
            ("test-api-key", "test-api-key", "rate limit or exhausted API quota"),
        ]
        for code, kind, expected in cases:
            for call, argument in [(openai_client.ask_json, []), (openai_client.embed, ["text"])]:
                with self.subTest(code=code, call=call.__name__):
                    self.body = {"error": {"code": code, "type": kind, "message": "Sensitive test-api-key"}}
                    before = len(self.requests)
                    with self.assertRaises(openai_client.ModelError) as caught:
                        call(argument)
                    message = str(caught.exception)
                    self.assertIn(expected, message)
                    self.assertNotIn("test-api-key", message)
                    self.assertEqual(len(self.requests), before + 1)


class CredentialTests(unittest.TestCase):
    def test_environment_key_takes_precedence_without_reading_file(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "environment-key"}, clear=True):
            with patch("openai_client.dotenv_values") as read:
                self.assertEqual(openai_client.api_key(), "environment-key")
                read.assert_not_called()

    def test_local_key_is_loaded_from_explicit_path_without_changing_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / ".env.local"
            contents = 'OPENAI_API_KEY="local-key"\nUNRELATED="${HOME}"\n'
            file.write_text(contents)
            with patch.dict(os.environ, {}, clear=True), patch("openai_client.ENV_FILE", file):
                self.assertEqual(openai_client.api_key(), "local-key")
                self.assertNotIn("OPENAI_API_KEY", os.environ)
            self.assertEqual(file.read_text(), contents)

    def test_connection_pins_api_destination_and_disables_retries(self):
        with patch.dict(os.environ, {"OPENAI_BASE_URL": "https://example.invalid"}):
            with patch("openai_client.api_key", return_value="test-api-key"):
                with patch("openai_client.OpenAI") as client:
                    openai_client.connect(12)
        client.assert_called_once_with(api_key="test-api-key", base_url="https://api.openai.com/v1",
                                       timeout=12, max_retries=0)

    def test_missing_key_fails_without_changing_database_or_outputs(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(StringIO()):
            with patch.dict(os.environ, {}, clear=True):
                with patch("openai_client.ENV_FILE", Path(directory) / "missing.env"):
                    with self.assertRaisesRegex(openai_client.ModelError, "Set OPENAI_API_KEY"):
                        openai_client.api_key()
                    arguments = ["prototype.py", "--domain", "arithmetic", "--output", directory,
                                 str(prototype.HERE / "examples/arithmetic.txt")]
                    with patch("sys.argv", arguments), patch("prototype.run") as run:
                        with patch("neo4j_client.connect") as connect:
                            self.assertEqual(prototype.main(), 1)
                    run.assert_not_called()
                    connect.assert_not_called()
                    self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
