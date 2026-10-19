"""CLI contract tests: output shape, exit codes, error envelope."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deepseek_web import cli
from deepseek_web.errors import APIError

SEARCH_RAW = {
    "results": [
        {
            "title": "Rayleigh scattering",
            "url": "https://example.com/sky",
            "summary": "Short waves scatter more.",
            "rerank_score": 0.87,
        }
    ]
}
FETCH_RAW = {"title": "Example Domain", "content": "Hello world"}


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    def search_raw(self, **kwargs):
        self.search_kwargs = kwargs
        return SEARCH_RAW

    def fetch_raw(self, url):
        self.fetch_url = url
        return FETCH_RAW


def run(argv, client=FakeClient):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(cli, "Client", client):
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(argv)
            except SystemExit as exc:  # argparse usage errors
                code = exc.code if isinstance(exc.code, int) else 1
    return code, out.getvalue(), err.getvalue()


class SearchCommandTests(unittest.TestCase):
    def test_json_output_is_machine_readable(self):
        code, out, err = run(["search", "why is the sky blue", "--count", "3"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertEqual(payload["query"], "why is the sky blue")
        self.assertEqual(payload["count"], 3)
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["rerank_score"], 0.87)

    def test_default_count_is_five(self):
        _, out, _ = run(["search", "q"])
        self.assertEqual(json.loads(out)["count"], 5)

    def test_text_format(self):
        code, out, _ = run(["search", "sky", "--format", "text"])
        self.assertEqual(code, 0)
        self.assertIn("1. Rayleigh scattering", out)
        self.assertIn("https://example.com/sky", out)

    def test_raw_dumps_api_payload(self):
        code, out, _ = run(["search", "sky", "--raw"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), SEARCH_RAW)

    def test_count_out_of_range_exits_2(self):
        code, out, err = run(["search", "sky", "--count", "0"], client=cli.Client)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)["error"]["type"], "usage_error")
        self.assertEqual(out, "")

    def test_non_integer_count_is_usage_error(self):
        code, _, _ = run(["search", "sky", "--count", "abc"])
        self.assertEqual(code, 2)

    def test_api_error_exits_4(self):
        class Boom(FakeClient):
            def search_raw(self, **kwargs):
                raise APIError("API error 401: nope", status_code=401)

        code, out, err = run(["search", "q"], client=Boom)
        self.assertEqual(code, 4)
        self.assertEqual(out, "")
        payload = json.loads(err)
        self.assertEqual(payload["error"]["status_code"], 401)
        self.assertEqual(payload["error"]["type"], "api_error")


class FetchCommandTests(unittest.TestCase):
    def test_json_output(self):
        code, out, _ = run(["fetch", "https://example.com"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["title"], "Example Domain")
        self.assertEqual(payload["content"], "Hello world")
        self.assertEqual(payload["url"], "https://example.com")

    def test_bad_scheme_exits_2(self):
        code, _, err = run(["fetch", "example.com"], client=cli.Client)
        self.assertEqual(code, 2)
        self.assertIn("http://", json.loads(err)["error"]["message"])


class ConfigTests(unittest.TestCase):
    def test_missing_key_exits_3(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}, clear=False), mock.patch(
            "deepseek_web.keys.candidate_env_files", return_value=[]
        ), mock.patch("deepseek_web.keys.SECRET_PATHS", ()):
            code, out, err = run(["search", "q"], client=cli.Client)
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        self.assertEqual(json.loads(err)["error"]["type"], "config_error")
        self.assertIn("DEEPSEEK_API_KEY", json.loads(err)["error"]["message"])


class DoctorTests(unittest.TestCase):
    def test_doctor_reports_missing_key(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}, clear=False):
            code, out, _ = run(["doctor"])
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertFalse(report["ready"])
        self.assertFalse(report["api_key_set"])
        self.assertTrue(report["problems"])

    def test_doctor_masks_key(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-abcdefgh1234"}, clear=False):
            _, out, _ = run(["doctor"])
        report = json.loads(out)
        self.assertTrue(report["ready"])
        self.assertEqual(report["api_key_hint"], "****1234")


class UsageTests(unittest.TestCase):
    def test_no_command_prints_help_and_exits_2(self):
        code, out, _ = run([])
        self.assertEqual(code, 2)
        self.assertIn("search", out)


ESCAPED_SEARCH_RAW = {
    "results": [
        {
            "title": "Sky",
            "url": "https://example.com/sky",
            # single backslash before each punctuation mark, as the API sends it
            "summary": "Why is the sky blue\\? Because air scatters blue light\\, mostly\\.",
        }
    ]
}
ESCAPED_FETCH_RAW = {
    "title": "Ask an Explainer",
    "content": "Q\\: why\\?\n\nA\\: Rayleigh scattering\\.",
}


class EscapedClient(FakeClient):
    def search_raw(self, **kwargs):
        return ESCAPED_SEARCH_RAW

    def fetch_raw(self, url):
        return ESCAPED_FETCH_RAW


class UnescapeTests(unittest.TestCase):
    def test_search_keeps_escapes_by_default(self):
        code, out, _ = run(["search", "q"], client=EscapedClient)
        self.assertEqual(code, 0)
        summary = json.loads(out)["results"][0]["summary"]
        self.assertIn(r"blue\?", summary)

    def test_search_unescape_flag_strips_escapes(self):
        code, out, _ = run(["search", "q", "--unescape"], client=EscapedClient)
        self.assertEqual(code, 0)
        summary = json.loads(out)["results"][0]["summary"]
        self.assertIn("blue?", summary)
        self.assertIn("light,", summary)
        self.assertNotIn("\\", summary)

    def test_fetch_unescape_flag_strips_escapes(self):
        code, out, _ = run(
            ["fetch", "https://example.com", "--unescape"], client=EscapedClient
        )
        self.assertEqual(code, 0)
        content = json.loads(out)["content"]
        self.assertIn("Q: why?", content)
        self.assertNotIn("\\", content)

    def test_unescape_applies_to_text_format(self):
        code, out, _ = run(
            ["fetch", "https://example.com", "--unescape", "--format", "text"],
            client=EscapedClient,
        )
        self.assertEqual(code, 0)
        self.assertIn("Q: why?", out)


if __name__ == "__main__":
    unittest.main()


class MaxCharsTests(unittest.TestCase):
    """The cap exists so one big page cannot flood an agent's context."""

    LONG = "x" * 50_000

    def _long_client(self):
        long = self.LONG

        class LongClient(FakeClient):
            def search_raw(self, **kwargs):
                return {
                    "results": [
                        {
                            "title": "Big",
                            "url": "https://example.com/big",
                            "summary": long,
                            "content": long,
                        }
                    ]
                }

            def fetch_raw(self, url):
                return {"title": "Big", "content": long}

        return LongClient

    def test_search_caps_summary_and_content(self):
        code, out, _ = run(["search", "q", "--max-chars", "100"], self._long_client())
        self.assertEqual(code, 0)
        result = json.loads(out)["results"][0]
        self.assertLess(len(result["summary"]), 200)
        self.assertLess(len(result["content"]), 200)
        self.assertIn("[truncated", result["summary"])

    def test_fetch_caps_content(self):
        code, out, _ = run(["fetch", "https://example.com/big", "--max-chars", "100"], self._long_client())
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertLess(len(payload["content"]), 200)
        self.assertIn("[truncated", payload["content"])

    def test_zero_disables_the_cap(self):
        code, out, _ = run(["fetch", "https://example.com/big", "--max-chars", "0"], self._long_client())
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)["content"]), len(self.LONG))

    def test_cap_keeps_json_valid(self):
        _, out, _ = run(["search", "q", "--max-chars", "10"], self._long_client())
        json.loads(out)  # raises if the marker broke escaping

    def test_negative_cap_is_a_usage_error(self):
        code, out, err = run(["search", "q", "--max-chars", "-5"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("max_chars", err)
