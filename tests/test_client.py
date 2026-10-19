"""Client tests with urllib mocked out - no network, no API key needed."""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
import urllib.error
from email.message import Message
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deepseek_web.client import Client, error_message
from deepseek_web.errors import APIError, ConfigError, NetworkError, ValidationError
from deepseek_web.models import FetchedPage, SearchResult


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def http_error(code: int, payload: dict, headers: dict | None = None):
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    body = io.BytesIO(json.dumps(payload).encode("utf-8"))
    return urllib.error.HTTPError("https://api.deepseek.com", code, "error", message, body)


SEARCH_PAYLOAD = {
    "results": [
        {
            "title": "Rayleigh scattering",
            "url": "https://example.com/sky",
            "summary": "Short waves scatter more.",
            "site_name": "Example",
            "date": "2026-01-02",
            "rerank_score": 0.87,
            "authority": 0.42,
        },
        {
            "title": "No score here",
            "url": "https://example.com/two",
        },
    ]
}


class ClientParsingTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}, clear=False)
        self.env.start()
        self.client = Client(api_base="https://api.test/v1/tools", retries=0)

    def tearDown(self):
        self.env.stop()

    def test_search_sends_expected_payload(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(SEARCH_PAYLOAD)) as opened:
            results = self.client.search("why is the sky blue", count=7, need_content=True)

        request = opened.call_args[0][0]
        sent = json.loads(request.data.decode("utf-8"))
        self.assertEqual(sent["query"], "why is the sky blue")
        self.assertEqual(sent["count"], 7)
        self.assertTrue(sent["need_content"])
        self.assertNotIn("ori_question", sent)
        self.assertEqual(request.full_url, "https://api.test/v1/tools/search")
        self.assertEqual(request.get_header("Authorization"), "Bearer sk-test")

        self.assertEqual(len(results), 2)
        self.assertIsInstance(results[0], SearchResult)
        self.assertEqual(results[0].rerank_score, 0.87)
        self.assertIsNone(results[1].rerank_score)
        self.assertEqual(results[1].authority, None)

    def test_ori_question_and_localization_forwarded(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse({"results": []})) as opened:
            self.client.search("q", ori_question="orig?", localization="en-US")
        sent = json.loads(opened.call_args[0][0].data.decode("utf-8"))
        self.assertEqual(sent["ori_question"], "orig?")
        self.assertEqual(sent["localization"], "en-US")

    def test_fetch_returns_page(self):
        payload = {"title": "Example Domain", "content": "Hello world"}
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(payload)) as opened:
            page = self.client.fetch("https://example.com")
        sent = json.loads(opened.call_args[0][0].data.decode("utf-8"))
        self.assertEqual(sent, {"url": "https://example.com"})
        self.assertIsInstance(page, FetchedPage)
        self.assertEqual(page.title, "Example Domain")
        self.assertEqual(page.url, "https://example.com")
        self.assertEqual(page.content, "Hello world")

    def test_validation_happens_before_network(self):
        with mock.patch("urllib.request.urlopen") as opened:
            with self.assertRaises(ValidationError):
                self.client.search("   ")
            with self.assertRaises(ValidationError):
                self.client.search("q", count=0)
            with self.assertRaises(ValidationError):
                self.client.fetch("ftp://example.com")
        opened.assert_not_called()

    def test_missing_key_raises_config_error(self):
        client = Client(api_base="https://api.test/v1/tools")
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}, clear=False):
            with self.assertRaises(ConfigError):
                client.search("q")

    def test_http_error_becomes_api_error(self):
        error = http_error(401, {"error": {"message": "Authentication Fails"}})
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(APIError) as ctx:
                self.client.search("q")
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("Authentication Fails", str(ctx.exception))

    def test_network_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("dns down")):
            with self.assertRaises(NetworkError):
                self.client.search("q")

    def test_non_json_body(self):
        response = FakeResponse({})
        response.read = lambda: b"<html>gateway</html>"
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(APIError):
                self.client.search("q")


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_retries_on_429_then_succeeds(self):
        error = http_error(429, {"error": {"message": "rate limited"}}, {"Retry-After": "0"})
        client = Client(api_base="https://api.test/v1/tools", retries=2)
        with mock.patch(
            "urllib.request.urlopen", side_effect=[error, FakeResponse(SEARCH_PAYLOAD)]
        ) as opened:
            results = client.search("q")
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(len(results), 2)

    def test_gives_up_after_retries(self):
        errors = [http_error(503, {"error": {"message": "unavailable"}}) for _ in range(3)]
        client = Client(api_base="https://api.test/v1/tools", retries=2)
        with mock.patch("urllib.request.urlopen", side_effect=errors) as opened:
            with self.assertRaises(APIError):
                client.search("q")
        self.assertEqual(opened.call_count, 3)


class ErrorMessageTests(unittest.TestCase):
    def test_extracts_nested_message(self):
        self.assertEqual(error_message('{"error": {"message": "boom"}}'), "boom")

    def test_falls_back_to_raw_body(self):
        self.assertEqual(error_message("plain text"), "plain text")
        self.assertEqual(error_message(""), "")


if __name__ == "__main__":
    unittest.main()
