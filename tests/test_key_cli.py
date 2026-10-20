"""CLI contract tests for the ``key`` command group."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deepseek_web.keys import ENV_VAR
from tests.test_cli import run

CLEAN_ENV = {
    "DEEPSEEK_API_KEY": "",
    "DEEPSEEK_API_KEY_FILE": "",
    "DEEPSEEK_API_KEY_CMD": "",
}



class KeyStatusTests(unittest.TestCase):
    def test_status_reports_dotenv_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(f"{ENV_VAR}=sk-status12345\n")
            with mock.patch.dict(os.environ, CLEAN_ENV, clear=False):
                code, out, _ = run(["key", "status", "--env-file", str(path)])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["source"]["source"], "dotenv")
        self.assertEqual(payload["api_key_hint"], "****2345")
        self.assertTrue(any(e["exists"] for e in payload["env_files"]))
        self.assertFalse(payload["api_key_encrypted"])

    def test_status_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.env"
            with mock.patch.dict(os.environ, CLEAN_ENV, clear=False), mock.patch(
                "deepseek_web.keys.candidate_env_files", return_value=[missing]
            ), mock.patch("deepseek_web.keys.SECRET_PATHS", ()):
                code, out, _ = run(["key", "status"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertFalse(payload["ready"])
        self.assertIn("error", payload)

    def test_status_json_never_contains_the_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(f"{ENV_VAR}=sk-supersecret9999\n")
            with mock.patch.dict(os.environ, CLEAN_ENV, clear=False):
                _, out, _ = run(["key", "status", "--env-file", str(path)])
        self.assertNotIn("supersecret", out)


class DoctorSourceTests(unittest.TestCase):
    def test_doctor_reports_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(f"{ENV_VAR}=sk-doctor123456\n")
            with mock.patch.dict(os.environ, CLEAN_ENV, clear=False):
                code, out, _ = run(["doctor", "--env-file", str(path)])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["api_key_source"]["source"], "dotenv")
        self.assertEqual(payload["api_key_hint"], "****3456")

    def test_doctor_without_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.env"
            with mock.patch.dict(os.environ, CLEAN_ENV, clear=False), mock.patch(
                "deepseek_web.keys.candidate_env_files", return_value=[missing]
            ), mock.patch("deepseek_web.keys.SECRET_PATHS", ()):
                code, out, _ = run(["doctor"])
        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertFalse(payload["ready"])
        self.assertIsNone(payload["api_key_source"])


class KeyUsageTests(unittest.TestCase):
    def test_key_without_action_is_usage_error(self):
        code, _, err = run(["key"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)["error"]["type"], "usage_error")


    def test_status_flags_a_wrapped_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(f"{ENV_VAR}=enc2:AAAABBBBCCCC\n")
            with mock.patch.dict(os.environ, CLEAN_ENV, clear=False):
                code, out, _ = run(["key", "status", "--env-file", str(path)])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertFalse(payload["ready"])
        self.assertTrue(payload["api_key_encrypted"])
        self.assertIn("wrapped secret", payload["error"])
        self.assertNotIn("AAAABBBBCCCC", out)



if __name__ == "__main__":
    unittest.main()
