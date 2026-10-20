"""deepseek-web: search and fetch the web through DeepSeek's tool API.

Zero dependencies, one CLI, JSON in / JSON out. Built to be dropped into
an agent runtime as a subprocess tool rather than exposed as an MCP server.
"""

from __future__ import annotations

from .client import (
    DEFAULT_API_BASE,
    DEFAULT_COUNT_CLI,
    DEFAULT_COUNT_LIBRARY,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT,
    Client,
    error_message,
    resolve_api_base,
    resolve_api_key,
)
from .errors import (
    APIError,
    ConfigError,
    DeepSeekError,
    EncryptedKeyError,
    NetworkError,
    ValidationError,
)
from .keys import (
    ENV_VAR as API_KEY_ENV_VAR,
    KeyResolution,
    candidate_env_files,
    looks_encrypted,
    parse_dotenv,
    resolve_key,
)
from .models import FetchedPage, SearchResult
from .validation import (
    MAX_COUNT,
    MAX_QUERY_LEN,
    MAX_URL_LEN,
    MIN_COUNT,
    parse_count,
    validate_count,
    validate_query,
    validate_url,
)

__version__ = "0.4.0"

__all__ = [
    "APIError",
    "Client",
    "ConfigError",
    "DEFAULT_API_BASE",
    "DEFAULT_COUNT_CLI",
    "DEFAULT_COUNT_LIBRARY",
    "DEFAULT_RETRIES",
    "DEFAULT_TIMEOUT",
    "DeepSeekError",
    "EncryptedKeyError",
    "FetchedPage",
    "MAX_COUNT",
    "MAX_QUERY_LEN",
    "MAX_URL_LEN",
    "MIN_COUNT",
    "NetworkError",
    "SearchResult",
    "ValidationError",
    "__version__",
    "error_message",
    "looks_encrypted",
    "parse_count",
    "resolve_api_base",
    "resolve_api_key",
    "validate_count",
    "validate_query",
    "validate_url",
]


def search(query: str, count: int = DEFAULT_COUNT_LIBRARY, **kwargs):
    """Convenience wrapper: ``deepseek_web.search("query", count=5)``."""
    return Client().search(query, count=count, **kwargs)


def fetch(url: str):
    """Convenience wrapper: ``deepseek_web.fetch("https://example.com")``."""
    return Client().fetch(url)
