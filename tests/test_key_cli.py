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


class KeySetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / ".env"

    def tearDown(self):
        self.tmp.cleanup()

    def test_set_writes_0600_and_reports_masked(self):
        with mock.patch.dict(os.environ, CLEAN_ENV, clear=False):
            code, out, err = run(
                ["key", "set", "--value", "sk-abcdefgh1234", "--path", str(self.path)]
            )
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertTrue(payload["stored"])
        self.assertEqual(payload["api_key_hint"], "****1234")
        self.assertEqual(payload["mode"], "0o600")
        self.assertIn("sk-abcdefgh1234", self.path.read_text())
        self.assertNotIn("sk-abcdefgh1234", out)

    def test_set_rejects_empty_value(self):
        with mock.patch.dict(os.environ, CLEAN_ENV, clear=False):
            code, out, err = run(
                ["key", "set", "--value", "   ", "--path", str(self.path)]
            )
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)["error"]["type"], "usage_error")
        self.assertFalse(self.path.exists())

    def test_set_rejects_whitespace_inside_key(self):
        with mock.patch.dict(os.environ, CLEAN_ENV, clear=False):
            code, _, _ = run(
                ["key", "set", "--value", "sk-two words", "--path", str(self.path)]
            )
        self.assertEqual(code, 2)

    def test_set_overwrites_existing_entry(self):
        self.path.write_text("OTHER=1\nDEEPSEEK_API_KEY=old\n")
        with mock.patch.dict(os.environ, CLEAN_ENV, clear=False):
            run(["key", "set", "--value", "sk-newkey12345", "--path", str(self.path)])
        text = self.path.read_text()
        self.assertIn("OTHER=1", text)
        self.assertNotIn("old", text)
        self.assertEqual(text.count("DEEPSEEK_API_KEY="), 1)


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
        self.assertIn("zeroclaw", payload)

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


class KeyClearTests(unittest.TestCase):
    def test_clear_removes_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(f"OTHER=1\n{ENV_VAR}=sk-abc\n")
            code, out, _ = run(["key", "clear", "--path", str(path)])
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(out)["removed"])
            self.assertNotIn("DEEPSEEK_API_KEY", path.read_text())
            self.assertIn("OTHER=1", path.read_text())

    def test_clear_on_missing_file_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = run(["key", "clear", "--path", str(Path(tmp) / "absent.env")])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["removed"])


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


if __name__ == "__main__":
    unittest.main()
