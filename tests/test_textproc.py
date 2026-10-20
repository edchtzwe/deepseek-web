"""Unit tests for markdown-escape stripping (no network)."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deepseek_web.textproc import strip_markdown_escapes


class StripMarkdownEscapesTests(unittest.TestCase):
    def test_strips_known_escapes(self):
        cases = [
            (r"Q\:", "Q:"),
            (r"Why is the sky blue\?", "Why is the sky blue?"),
            (r"Posted on January 23\, 2018", "Posted on January 23, 2018"),
            (r"tiny particles\. Blue", "tiny particles. Blue"),
            (r"\#\# Heading", "## Heading"),
            (r"a\.b\.c", "a.b.c"),
            (r"\*not italic\*", "*not italic*"),
            (r"brackets \[x\]", "brackets [x]"),
            (r"a\-b\+c\!d", "a-b+c!d"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(strip_markdown_escapes(raw), expected)

    def test_plain_prose_untouched(self):
        text = "The sky is blue because of Rayleigh scattering."
        self.assertEqual(strip_markdown_escapes(text), text)

    def test_unknown_escape_preserved(self):
        # \n as a literal backslash-n should survive: "n" is not markdown-escaped.
        self.assertEqual(strip_markdown_escapes(r"line\nbreak"), r"line\nbreak")

    def test_windows_path_preserved(self):
        self.assertEqual(strip_markdown_escapes(r"C:\Users\x"), r"C:\Users\x")

    def test_code_fence_preserved(self):
        text = "```python\nprint(1)\n```"
        self.assertEqual(strip_markdown_escapes(text), text)

    def test_backslash_escape_collapsed(self):
        self.assertEqual(strip_markdown_escapes(r"a\\b"), r"a\b")

    def test_idempotent(self):
        once = strip_markdown_escapes(r"Why blue\? Really\.")
        self.assertEqual(strip_markdown_escapes(once), once)

    def test_empty_values_pass_through(self):
        for value in ("", None):
            with self.subTest(value=value):
                self.assertEqual(strip_markdown_escapes(value), value)


if __name__ == "__main__":
    unittest.main()
