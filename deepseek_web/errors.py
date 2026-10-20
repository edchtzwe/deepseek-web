"""Exception hierarchy for the deepseek-web tool.

Every error the CLI can surface maps to exactly one subclass, and each
subclass maps to one process exit code in :mod:`deepseek_web.cli`.
"""

from __future__ import annotations

from typing import Optional


class DeepSeekError(Exception):
    """Base class for every error raised by this package."""


class ConfigError(DeepSeekError):
    """Bad or missing local configuration (API key, base URL, timeout)."""


class EncryptedKeyError(ConfigError):
    """The resolved value is an encrypted blob, not a usable plaintext key."""


class ValidationError(DeepSeekError):
    """Caller supplied an argument the API would reject."""


class NetworkError(DeepSeekError):
    """The request never produced an HTTP response."""


class APIError(DeepSeekError):
    """The API returned a non-2xx status or an unparseable body."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        body: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body

    def __str__(self) -> str:  # pragma: no cover - mirror of message
        return str(self.args[0]) if self.args else super().__str__()
