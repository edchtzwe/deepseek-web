"""Tests for markdown-escape stripping."""

from __future__ import annotations

import pytest

from deepseek_web.textproc import strip_markdown_escapes


@pytest.mark.parametrize(
    "raw,expected",
    [
        (r"Q\:", "Q:"),
        (r"Why is the sky blue\?", "Why is the sky blue?"),
        (r"Posted on January 23\, 2018", "Posted on January 23, 2018"),
        (r"tiny particles\. Blue", "tiny particles. Blue"),
        (r"\#\# Heading", "## Heading"),
        (r"a\.b\.c", "a.b.c"),
        (r"\*not italic\*", "*not italic*"),
        (r"brackets \[x\]", "brackets [x]"),
        (r"a\-b\+c\!d", "a-b+c!d"),
    ],
)
def test_strips_known_escapes(raw: str, expected: str) -> None:
    assert strip_markdown_escapes(raw) == expected


def test_plain_prose_untouched() -> None:
    text = "The sky is blue because of Rayleigh scattering."
    assert strip_markdown_escapes(text) == text


def test_unknown_escape_preserved() -> None:
    # \n as a literal backslash-n should survive: "n" is not markdown-escaped.
    assert strip_markdown_escapes(r"line\nbreak") == r"line\nbreak"


def test_windows_path_preserved() -> None:
    assert strip_markdown_escapes(r"C:\Users\x") == r"C:\Users\x"


def test_code_fence_preserved() -> None:
    text = "```python\nprint(1)\n```"
    assert strip_markdown_escapes(text) == text


def test_backslash_escape_collapsed() -> None:
    assert strip_markdown_escapes(r"a\\b") == r"a\b"


def test_idempotent() -> None:
    once = strip_markdown_escapes(r"Why blue\? Really\.")
    assert strip_markdown_escapes(once) == once


@pytest.mark.parametrize("value", ["", None])
def test_empty_values_pass_through(value) -> None:
    assert strip_markdown_escapes(value) == value
