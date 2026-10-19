"""Text normalisation helpers for tool output.

DeepSeek's tool API returns page content as markdown with punctuation
backslash-escaped (``Why is the sky blue\\?``). That is valid markdown but
reads as noise to an agent consuming the text as plain prose, so callers can
opt into stripping it.
"""

from __future__ import annotations

import re
from typing import Optional

# Characters markdown escapes. Only these are unescaped, so a genuine
# backslash before some other character is left alone.
_MD_ESCAPABLE = r"""\\`*_{}\[\]()#+\-.!?:,<>|~$"'&;=/@^%"""
_ESCAPE_RE = re.compile(rf"\\([{_MD_ESCAPABLE}])")


def strip_markdown_escapes(text: Optional[str]) -> Optional[str]:
    """Remove backslashes that markdown uses to escape punctuation.

    Idempotent and conservative: only ``\\<punctuation>`` sequences are
    touched, so ordinary prose and code fences survive intact.
    """
    if not text:
        return text
    return _ESCAPE_RE.sub(r"\1", text)
