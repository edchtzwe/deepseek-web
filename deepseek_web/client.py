"""HTTP client for DeepSeek's server-side Search and Fetch tools.

Stdlib only: one file an agent can drop onto a box with Python 3.9+ and
no package manager. No MCP, no daemon, no config file - environment
variables in, JSON out.
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .errors import APIError, ConfigError, NetworkError
from .keys import resolve_key
from .models import FetchedPage, SearchResult, results_from_payload
from .validation import validate_count, validate_optional_query, validate_query, validate_url

DEFAULT_API_BASE = "https://api.deepseek.com/v1/tools"
DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRIES = 2
DEFAULT_COUNT_LIBRARY = 10
DEFAULT_COUNT_CLI = 5

#: Statuses worth a retry. The API allows 5 QPS, so 429 is expected traffic.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

API_KEY_ENV = "DEEPSEEK_API_KEY"
API_BASE_ENV = "DEEPSEEK_API_BASE"
TIMEOUT_ENV = "DEEPSEEK_TIMEOUT"
RETRIES_ENV = "DEEPSEEK_RETRIES"


def resolve_api_key(
    api_key: Optional[str] = None,
    env_file: Optional[str] = None,
    use_env_files: bool = True,
) -> str:
    """Resolve a key from the full source chain (see :mod:`deepseek_web.keys`)."""
    return resolve_key(
        explicit=api_key,
        env_file=Path(env_file) if env_file else None,
        use_env_files=use_env_files,
    ).key


def resolve_api_base(api_base: Optional[str] = None) -> str:
    base = (api_base or os.getenv(API_BASE_ENV) or DEFAULT_API_BASE).strip()
    if not base.lower().startswith(("http://", "https://")):
        raise ConfigError(f"API base must start with http:// or https:// (got {base!r})")
    return base.rstrip("/")


def error_message(body: str) -> str:
    """Pull the human-readable message out of an API error body."""
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return body.strip()
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping) and error.get("message"):
            return str(error["message"])
        if isinstance(error, str) and error:
            return error
        if payload.get("message"):
            return str(payload["message"])
    return body.strip()


class Client:
    """Thin, synchronous DeepSeek tools client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: Optional[float] = None,
        retries: Optional[int] = None,
        env_file: Optional[str] = None,
        use_env_files: bool = True,
    ) -> None:
        self._api_key = api_key
        self.env_file = env_file
        self.use_env_files = use_env_files
        self.api_base = resolve_api_base(api_base)
        self.timeout = DEFAULT_TIMEOUT if timeout is None else float(timeout)
        self.retries = DEFAULT_RETRIES if retries is None else max(0, int(retries))

    # -- configuration ---------------------------------------------------

    @property
    def api_key(self) -> str:
        """Resolved lazily so `doctor` can run without one."""
        return resolve_api_key(
            self._api_key, env_file=self.env_file, use_env_files=self.use_env_files
        )

    # -- public API ------------------------------------------------------

    def search_raw(
        self,
        query: str,
        count: int = DEFAULT_COUNT_LIBRARY,
        ori_question: Optional[str] = None,
        localization: str = "",
        need_content: bool = False,
    ) -> Dict[str, Any]:
        """POST /search and return the untouched response object."""
        payload: Dict[str, Any] = {
            "query": validate_query(query),
            "count": validate_count(count),
            "need_content": bool(need_content),
        }
        if ori_question is not None:
            payload["ori_question"] = validate_optional_query(ori_question, "ori_question")
        if localization:
            payload["localization"] = validate_query(localization, field="localization")
        return self._post("/search", payload)

    def search(
        self,
        query: str,
        count: int = DEFAULT_COUNT_LIBRARY,
        ori_question: Optional[str] = None,
        localization: str = "",
        need_content: bool = False,
    ) -> List[SearchResult]:
        """Search the web and return typed results."""
        return results_from_payload(
            self.search_raw(query, count, ori_question, localization, need_content)
        )

    def fetch_raw(self, url: str) -> Dict[str, Any]:
        """POST /fetch and return the untouched response object."""
        return self._post("/fetch", {"url": validate_url(url)})

    def fetch(self, url: str) -> FetchedPage:
        """Fetch and extract one page."""
        target = validate_url(url)
        return FetchedPage.from_payload(self._post("/fetch", {"url": target}), url=target)

    # -- transport -------------------------------------------------------

    def _post(self, endpoint: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        url = f"{self.api_base}{endpoint}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": f"deepseek-web/0.1 (+python-urllib)",
        }

        attempt = 0
        while True:
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                break
            except urllib.error.HTTPError as exc:
                raw_error = exc.read().decode("utf-8", errors="replace")
                if exc.code in RETRY_STATUSES and attempt < self.retries:
                    time.sleep(self._retry_delay(exc, attempt))
                    attempt += 1
                    continue
                raise APIError(
                    f"API error {exc.code}: {error_message(raw_error)}",
                    status_code=exc.code,
                    body=raw_error,
                ) from exc
            except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
                reason = getattr(exc, "reason", exc)
                if isinstance(reason, str) and "timed out" in reason.lower() and attempt < self.retries:
                    time.sleep(self._retry_delay(None, attempt))
                    attempt += 1
                    continue
                raise NetworkError(f"network error: {reason}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise APIError("API returned a non-JSON body", body=raw) from exc
        if not isinstance(data, dict):
            raise APIError("API returned a JSON value that is not an object", body=raw)
        return data

    @staticmethod
    def _retry_delay(exc: Optional[urllib.error.HTTPError], attempt: int) -> float:
        """Prefer Retry-After, fall back to 0.5s / 1.5s / 3.5s."""
        if exc is not None:
            header = exc.headers.get("Retry-After") if exc.headers else None
            if header:
                try:
                    return max(0.0, min(float(header), 30.0))
                except ValueError:
                    pass
        return 0.5 * (3 ** attempt)
