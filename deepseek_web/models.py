"""Typed views over the DeepSeek Search / Fetch responses.

Field names were verified against live responses on 2026-10-19:
``/v1/tools/search`` returns ``title, url, summary, content, site_name,
date, rerank_score, authority, snippet, site_icon``; ``/v1/tools/fetch``
returns ``url, title, content``. Fields the tool does not model explicitly
(``snippet``, ``site_icon``, and anything DeepSeek adds later) are preserved
under ``extra`` so nothing is silently dropped.

Parsing stays tolerant anyway: missing or wrongly typed fields degrade to
``None`` / empty values instead of raising, so an agent still gets usable
output if DeepSeek renames something. Use ``--raw`` to inspect the untouched
payload when that matters.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


@dataclass(frozen=True)
class SearchResult:
    """One entry of a ``/v1/tools/search`` response."""

    title: str = ""
    url: str = ""
    summary: str = ""
    content: str = ""
    site_name: str = ""
    date: str = ""
    rerank_score: Optional[float] = None
    authority: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "SearchResult":
        known = {
            "title",
            "url",
            "summary",
            "content",
            "site_name",
            "date",
            "rerank_score",
            "authority",
        }
        extra = {k: v for k, v in payload.items() if k not in known}
        return cls(
            title=_as_str(payload.get("title")),
            url=_as_str(payload.get("url")),
            summary=_as_str(payload.get("summary")),
            content=_as_str(payload.get("content")),
            site_name=_as_str(payload.get("site_name")),
            date=_as_str(payload.get("date")),
            rerank_score=_as_float(payload.get("rerank_score")),
            authority=_as_float(payload.get("authority")),
            extra=extra,
        )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Keep the agent-facing schema stable: always emit the known keys,
        # only add `extra` when the API sent something we did not model.
        if not data["extra"]:
            del data["extra"]
        return data


@dataclass(frozen=True)
class FetchedPage:
    """Result of a ``/v1/tools/fetch`` call."""

    url: str = ""
    title: str = ""
    content: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any], url: str = "") -> "FetchedPage":
        extra = {
            k: v
            for k, v in payload.items()
            if k not in {"title", "content", "url"}
        }
        return cls(
            url=_as_str(payload.get("url")) or url,
            title=_as_str(payload.get("title")),
            content=_as_str(payload.get("content")),
            extra=extra,
        )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if not data["extra"]:
            del data["extra"]
        return data


def results_from_payload(payload: Mapping[str, Any]) -> List[SearchResult]:
    raw = payload.get("results")
    if not isinstance(raw, list):
        return []
    return [
        SearchResult.from_payload(item)
        for item in raw
        if isinstance(item, Mapping)
    ]
