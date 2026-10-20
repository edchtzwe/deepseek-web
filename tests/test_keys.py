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
from deepseek_web.errors import ConfigError, EncryptedKeyError
from deepseek_web.keys import (
    ENV_VAR,
    candidate_env_files,
    looks_encrypted,
    parse_dotenv,
    read_key_file,
    resolve_key,
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


class ReadKeyFileTests(unittest.TestCase):
    """A bare key file is read by skipping comments, not by rejecting them."""

    def _keyfile(self, text: str) -> "Path":
        tmp = tempfile.NamedTemporaryFile("w", suffix=".key", delete=False)
        tmp.write(text)
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        return Path(tmp.name)

    def test_leading_comment_does_not_hide_the_key(self):
        path = self._keyfile("# my deepseek key\nsk-live\n")
        self.assertEqual(read_key_file(path), "sk-live")

    def test_comment_block_then_key(self):
        path = self._keyfile("\n# note\n# another note\n\n  sk-live  \n")
        self.assertEqual(read_key_file(path), "sk-live")

    def test_commented_candidate_is_never_returned(self):
        path = self._keyfile("#DEEPSEEK_API_KEY=sk-commented\n")
        self.assertIsNone(read_key_file(path))

    def test_env_style_line_still_wins(self):
        path = self._keyfile("# leading\nDEEPSEEK_API_KEY=sk-eq\n")
        self.assertEqual(read_key_file(path), "sk-eq")

    def test_empty_file_is_none(self):
        self.assertIsNone(read_key_file(self._keyfile("")))


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
        message = str(ctx.exception)
        self.assertIn(ENV_VAR, message)
        self.assertIn("DEEPSEEK_API_KEY_CMD", message)
        # The tool never offers to provision; provisioning is the user's job.
        self.assertNotIn("key set", message)

    def test_no_env_files_flag(self):
        self.assertEqual(resolve_key(use_env_files=False).source, "secret")

    def test_masked_never_leaks_middle(self):
        os.environ[ENV_VAR] = "sk-abcdefghijkl1234"
        resolution = resolve_key()
        self.assertEqual(resolution.masked, "****1234")
        self.assertNotIn("abcdef", resolution.masked)


class LooksEncryptedTests(unittest.TestCase):
    """Wrapped secrets are refused before they can burn a request on a 401."""

    def test_recognises_common_wrappers(self):
        for value in (
            "enc2:AAAABBBBCCCCDDDD",
            "enc:abc",
            "encrypted:abc",
            "gpg:hQEMA1234",
            "age:YWdlLWVuY3J5cHRpb24=",
            "vault:v1:abc",
            "sops:abc",
            "sealed:abc",
            "base64:c2stZmFrZQ==",
            "ENC2:UPPER",
        ):
            self.assertTrue(looks_encrypted(value), value)

    def test_accepts_real_key_shapes(self):
        for value in (
            "sk-fc51aa00bb11cc22dd33ee44ff556dd2",
            "sk-proj-abc123",
            "plain-token",
            "eyJhbGciOiJIUzI1NiJ9.payload.sig",
        ):
            self.assertFalse(looks_encrypted(value), value)

    def test_empty_is_not_encrypted(self):
        self.assertFalse(looks_encrypted(""))

    def test_message_never_contains_the_value(self):
        secret = "enc2:SUPERSECRETBLOB"
        message = keys.encrypted_key_message(secret)
        self.assertIn("enc2:", message)
        self.assertNotIn("SUPERSECRETBLOB", message)

    def test_resolve_refuses_env_wrapped_secret(self):
        env = {ENV_VAR: "enc2:AAAABBBB"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch(
            "deepseek_web.keys.SECRET_PATHS", ()
        ):
            with self.assertRaises(EncryptedKeyError):
                resolve_key(use_env_files=False)

    def test_resolve_refuses_dotenv_wrapped_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(f"{ENV_VAR}=enc2:AAAABBBB\n")
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
                "deepseek_web.keys.SECRET_PATHS", ()
            ):
                with self.assertRaises(EncryptedKeyError):
                    resolve_key(env_file=path)

    def test_resolve_still_accepts_real_key(self):
        with mock.patch.dict(os.environ, {ENV_VAR: "sk-abcdef123456"}, clear=True):
            resolution = resolve_key(use_env_files=False)
        self.assertEqual(resolution.source, "env")


if __name__ == "__main__":
    unittest.main()
