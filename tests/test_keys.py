"""Credential discovery tests: precedence, .env parsing, safe writes."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deepseek_web import keys
from deepseek_web.errors import ConfigError
from deepseek_web.keys import (
    ENV_VAR,
    candidate_env_files,
    diagnose_zeroclaw,
    parse_dotenv,
    read_env_file,
    remove_env_key,
    resolve_key,
    write_env_file,
)


class ParseDotenvTests(unittest.TestCase):
    def test_basic_and_comments(self):
        text = "\n".join(
            [
                "# comment",
                "",
                "DEEPSEEK_API_KEY=sk-abc",
                "OTHER=1",
                "  SPACED = value  ",
            ]
        )
        parsed = parse_dotenv(text)
        self.assertEqual(parsed["DEEPSEEK_API_KEY"], "sk-abc")
        self.assertEqual(parsed["OTHER"], "1")
        self.assertEqual(parsed["SPACED"], "value")

    def test_export_and_quotes(self):
        parsed = parse_dotenv(
            'export A="has space"\nB=\'single\'\nC=plain # trailing\n'
        )
        self.assertEqual(parsed["A"], "has space")
        self.assertEqual(parsed["B"], "single")
        self.assertEqual(parsed["C"], "plain")

    def test_ignores_malformed_lines(self):
        parsed = parse_dotenv("not an assignment\n=novalue\nOK=1\n")
        self.assertEqual(parsed, {"OK": "1"})


class CandidateEnvFileTests(unittest.TestCase):
    def test_walks_upwards_and_puts_cwd_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "a" / "b"
            nested.mkdir(parents=True)
            paths = candidate_env_files(cwd=nested)
            self.assertEqual(paths[0], nested / ".env")
            self.assertIn(root / ".env", paths)
            self.assertEqual(len(paths), len(set(paths)))

    def test_explicit_override_comes_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.dict(os.environ, {"DEEPSEEK_WEB_ENV_FILE": str(root / "custom.env")}):
                paths = candidate_env_files(cwd=root)
            self.assertEqual(paths[0], root / "custom.env")


class ResolutionPrecedenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dotenv = self.root / ".env"
        self.dotenv.write_text(f"{ENV_VAR}=sk-dotenv\n")
        self.keyfile = self.root / "key.txt"
        self.keyfile.write_text("sk-file\n")
        self.secret = self.root / "secret"
        self.secret.write_text("sk-secret\n")

        self.env_patch = mock.patch.dict(os.environ, {}, clear=False)
        self.env_patch.start()
        for var in ("DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY_FILE", "DEEPSEEK_API_KEY_CMD"):
            os.environ.pop(var, None)
        self.secret_patch = mock.patch.object(keys, "SECRET_PATHS", (str(self.secret),))
        self.secret_patch.start()
        self.files_patch = mock.patch.object(
            keys, "candidate_env_files", return_value=[self.dotenv]
        )
        self.files_patch.start()

    def tearDown(self):
        self.files_patch.stop()
        self.secret_patch.stop()
        self.env_patch.stop()
        self.tmp.cleanup()

    def test_explicit_argument_wins(self):
        os.environ[ENV_VAR] = "sk-env"
        self.assertEqual(resolve_key(explicit="sk-arg").source, "argument")

    def test_env_beats_dotenv(self):
        os.environ[ENV_VAR] = "sk-env"
        resolution = resolve_key()
        self.assertEqual(resolution.key, "sk-env")
        self.assertEqual(resolution.source, "env")

    def test_empty_env_is_treated_as_missing(self):
        os.environ[ENV_VAR] = ""
        self.assertEqual(resolve_key().source, "dotenv")

    def test_key_file(self):
        self.assertEqual(resolve_key(key_file=self.keyfile).source, "file")

    def test_key_file_from_env(self):
        os.environ["DEEPSEEK_API_KEY_FILE"] = str(self.keyfile)
        self.assertEqual(resolve_key().source, "file")

    def test_command_source(self):
        os.environ["DEEPSEEK_API_KEY_CMD"] = "printf 'sk-command\\n'"
        resolution = resolve_key()
        self.assertEqual(resolution.key, "sk-command")
        self.assertEqual(resolution.source, "command")

    def test_failing_command_raises(self):
        os.environ["DEEPSEEK_API_KEY_CMD"] = "exit 3"
        with self.assertRaises(ConfigError):
            resolve_key()

    def test_dotenv_then_secret(self):
        self.assertEqual(resolve_key().key, "sk-dotenv")
        self.dotenv.unlink()
        self.assertEqual(resolve_key().source, "secret")

    def test_nothing_found_message_is_actionable(self):
        self.dotenv.unlink()
        self.secret.unlink()
        with self.assertRaises(ConfigError) as ctx:
            resolve_key()
        self.assertIn("key set", str(ctx.exception))

    def test_no_env_files_flag(self):
        self.assertEqual(resolve_key(use_env_files=False).source, "secret")

    def test_masked_never_leaks_middle(self):
        os.environ[ENV_VAR] = "sk-abcdefghijkl1234"
        resolution = resolve_key()
        self.assertEqual(resolution.masked, "****1234")
        self.assertNotIn("abcdef", resolution.masked)


class EnvFileWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / ".env"

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_0600_and_roundtrips(self):
        write_env_file(self.path, {ENV_VAR: "sk-12345678"})
        self.assertEqual(read_env_file(self.path), "sk-12345678")
        if os.name == "posix":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_preserves_other_entries(self):
        self.path.write_text("OTHER=keep\nDEEPSEEK_API_KEY=old\n")
        write_env_file(self.path, {ENV_VAR: "new"})
        text = self.path.read_text()
        self.assertIn("OTHER=keep", text)
        self.assertIn("DEEPSEEK_API_KEY=new", text)
        self.assertEqual(text.count("DEEPSEEK_API_KEY="), 1)

    def test_appends_when_absent(self):
        self.path.write_text("OTHER=1\n")
        write_env_file(self.path, {ENV_VAR: "sk-abc"})
        self.assertEqual(read_env_file(self.path), "sk-abc")

    def test_quotes_values_with_spaces(self):
        write_env_file(self.path, {ENV_VAR: 'sk-with "quote"'})
        self.assertEqual(read_env_file(self.path), 'sk-with "quote"')

    def test_remove(self):
        write_env_file(self.path, {ENV_VAR: "sk-abc"})
        self.assertTrue(remove_env_key(self.path))
        self.assertFalse(remove_env_key(self.path))
        self.assertIsNone(read_env_file(self.path))


class ZeroclawDiagnosisTests(unittest.TestCase):
    def test_detects_encrypted_provider_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text(
                '[providers.models.deepseek.flash]\n'
                'api_key = "enc2:AAAABBBBCCCC"\n'
                'model = "deepseek-flash"\n'
            )
            report = diagnose_zeroclaw(config)
        self.assertTrue(report["exists"])
        self.assertEqual(report["provider_keys"], 1)
        self.assertEqual(report["encrypted"], [True])
        self.assertIn("shell_env_passthrough", report["note"])

    def test_detects_plaintext_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text('[providers.models.deepseek.flash]\napi_key = "sk-plain"\n')
            report = diagnose_zeroclaw(config)
        self.assertEqual(report["encrypted"], [False])
        self.assertNotIn("note", report)

    def test_missing_config_is_not_an_error(self):
        report = diagnose_zeroclaw(Path("/nonexistent/config.toml"))
        self.assertFalse(report["exists"])


if __name__ == "__main__":
    unittest.main()
