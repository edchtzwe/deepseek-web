"""Input validation shared by the library and the CLI.

Limits come from the DeepSeek tool API docs. They live here once so the
library, the CLI, and the tests cannot drift apart.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlsplit

from .errors import ValidationError

MAX_QUERY_LEN = 128
MAX_URL_LEN = 8192
MIN_COUNT = 1
MAX_COUNT = 50

#: Per-field cap applied to ``summary`` / ``content`` before they reach the
#: caller. A single ``--need-content`` result can be tens of thousands of
#: characters; an agent that pipes that into its context pays for it on every
#: later turn. ``0`` (or ``--max-chars 0``) disables the cap, and ``--raw``
#: always returns the untouched payload.
DEFAULT_MAX_CHARS = 8000
TRUNCATION_MARKER = "\n…[truncated {removed} chars]"


def validate_query(query: str, field: str = "query") -> str:
    """Return the stripped query or raise :class:`ValidationError`."""
    if not isinstance(query, str):
        raise ValidationError(f"{field} must be a string")
    stripped = query.strip()
    if not stripped:
        raise ValidationError(f"{field} must not be empty or whitespace only")
    if len(stripped) > MAX_QUERY_LEN:
        raise ValidationError(f"{field} must be {MAX_QUERY_LEN} characters or less")
    return stripped


def validate_count(count: int) -> int:
    """Return the count or raise :class:`ValidationError`."""
    if isinstance(count, bool) or not isinstance(count, int):
        raise ValidationError("count must be an integer")
    if count < MIN_COUNT or count > MAX_COUNT:
        raise ValidationError(f"count must be between {MIN_COUNT} and {MAX_COUNT}")
    return count


def parse_count(raw: str) -> int:
    """Parse a CLI count argument, rejecting anything non-numeric."""
    if not isinstance(raw, str) or not raw.strip().isdigit():
        raise ValidationError("count must be an integer")
    return validate_count(int(raw.strip()))


def validate_url(url: str) -> str:
    """Return the URL or raise :class:`ValidationError`."""
    if not isinstance(url, str):
        raise ValidationError("URL must be a string")
    candidate = url.strip()
    if not candidate:
        raise ValidationError("URL must not be empty")
    if len(candidate) > MAX_URL_LEN:
        raise ValidationError(f"URL must be {MAX_URL_LEN} characters or less")
    if not candidate.lower().startswith(("http://", "https://")):
        raise ValidationError("URL must start with http:// or https://")
    parts = urlsplit(candidate)
    if not parts.netloc:
        raise ValidationError("URL must include a host")
    if parts.username or parts.password:
        raise ValidationError("URL must not contain a username or password")
    return candidate


def validate_max_chars(value: int) -> int:
    """Return the per-field character cap (``0`` means unlimited)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("max_chars must be an integer")
    if value < 0:
        raise ValidationError("max_chars must be 0 (unlimited) or a positive integer")
    return value


def truncate_text(text: str, max_chars: int) -> str:
    """Cap ``text`` at ``max_chars``, appending an explicit size marker.

    The marker matters more than the truncation: it tells the caller the text
    is incomplete, so an agent does not treat a clipped page as the whole page.
    """
    if not text or max_chars <= 0 or len(text) <= max_chars:
        return text
    removed = len(text) - max_chars
    return text[:max_chars] + TRUNCATION_MARKER.format(removed=removed)


def validate_optional_query(value: Optional[str], field: str) -> Optional[str]:
    """Validate an optional query-like field, preserving ``None``."""
    if value is None:
        return None
    return validate_query(value, field=field)
