"""Unit tests for validation helpers (no network)."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deepseek_web.errors import ValidationError
from deepseek_web.validation import (
    DEFAULT_MAX_CHARS,
    MAX_COUNT,
    MAX_QUERY_LEN,
    MAX_URL_LEN,
    parse_count,
    truncate_text,
    validate_count,
    validate_max_chars,
    validate_query,
    validate_url,
)


class ValidateQueryTests(unittest.TestCase):
    def test_strips_whitespace(self):
        self.assertEqual(validate_query("  rust async  "), "rust async")

    def test_rejects_empty(self):
        for value in ("", "   ", "\n\t"):
            with self.assertRaises(ValidationError):
                validate_query(value)

    def test_rejects_over_limit(self):
        validate_query("a" * MAX_QUERY_LEN)
        with self.assertRaises(ValidationError):
            validate_query("a" * (MAX_QUERY_LEN + 1))

    def test_rejects_non_string(self):
        with self.assertRaises(ValidationError):
            validate_query(None)  # type: ignore[arg-type]

    def test_field_name_appears_in_error(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_query(" ", field="ori_question")
        self.assertIn("ori_question", str(ctx.exception))


class ValidateCountTests(unittest.TestCase):
    def test_accepts_bounds(self):
        self.assertEqual(validate_count(1), 1)
        self.assertEqual(validate_count(MAX_COUNT), MAX_COUNT)

    def test_rejects_out_of_range(self):
        for value in (0, -1, MAX_COUNT + 1):
            with self.assertRaises(ValidationError):
                validate_count(value)

    def test_rejects_bool_and_float(self):
        for value in (True, 5.0):
            with self.assertRaises(ValidationError):
                validate_count(value)  # type: ignore[arg-type]

    def test_parse_count(self):
        self.assertEqual(parse_count("7"), 7)
        for raw in ("0", "51", "-3", "abc", "", "3.5"):
            with self.assertRaises(ValidationError):
                parse_count(raw)


class ValidateUrlTests(unittest.TestCase):
    def test_accepts_http_and_https(self):
        self.assertEqual(validate_url("https://example.com"), "https://example.com")
        self.assertEqual(validate_url("http://example.com/a?b=c"), "http://example.com/a?b=c")

    def test_rejects_scheme(self):
        for value in ("ftp://example.com", "example.com", "//example.com"):
            with self.assertRaises(ValidationError):
                validate_url(value)

    def test_rejects_credentials(self):
        with self.assertRaises(ValidationError):
            validate_url("https://user:pass@example.com")

    def test_rejects_empty_and_long(self):
        with self.assertRaises(ValidationError):
            validate_url("")
        with self.assertRaises(ValidationError):
            validate_url("https://example.com/" + "a" * MAX_URL_LEN)

    def test_requires_host(self):
        with self.assertRaises(ValidationError):
            validate_url("https://")


if __name__ == "__main__":
    unittest.main()


class TruncateTextTests(unittest.TestCase):
    def test_short_text_is_untouched(self):
        self.assertEqual(truncate_text("hello", 10), "hello")

    def test_zero_means_unlimited(self):
        text = "a" * 50
        self.assertEqual(truncate_text(text, 0), text)

    def test_empty_text_is_untouched(self):
        self.assertEqual(truncate_text("", 5), "")

    def test_truncates_and_marks_removed_length(self):
        capped = truncate_text("a" * 100, 10)
        self.assertTrue(capped.startswith("a" * 10))
        self.assertIn("[truncated 90 chars]", capped)

    def test_exact_length_is_not_truncated(self):
        text = "a" * 10
        self.assertEqual(truncate_text(text, 10), text)


class ValidateMaxCharsTests(unittest.TestCase):
    def test_default_is_positive(self):
        self.assertGreater(DEFAULT_MAX_CHARS, 0)

    def test_accepts_zero_and_positive(self):
        self.assertEqual(validate_max_chars(0), 0)
        self.assertEqual(validate_max_chars(500), 500)

    def test_rejects_negative_and_non_integer(self):
        for value in (-1, "10", None, True):
            with self.assertRaises(ValidationError):
                validate_max_chars(value)  # type: ignore[arg-type]
