"""Command-line interface.

Design rules for agent consumption:
  * JSON on stdout by default, one object per invocation.
  * Errors on stderr, machine-readable, with a documented exit code.
  * No prompts, no config files, no interactive state.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import __version__
from .client import (
    API_BASE_ENV,
    API_KEY_ENV,
    DEFAULT_API_BASE,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT,
    Client,
    resolve_api_base,
)
from .errors import APIError, ConfigError, DeepSeekError, NetworkError, ValidationError
from .keys import (
    ENV_VAR,
    candidate_env_files,
    diagnose_zeroclaw,
    resolve_key,
    write_env_file,
    remove_env_key,
)
from .models import FetchedPage, SearchResult
from .textproc import strip_markdown_escapes
from .validation import DEFAULT_MAX_CHARS, truncate_text, validate_max_chars

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_CONFIG = 3
EXIT_API = 4
EXIT_NETWORK = 5

EXIT_CODES = {
    ValidationError: EXIT_USAGE,
    ConfigError: EXIT_CONFIG,
    APIError: EXIT_API,
    NetworkError: EXIT_NETWORK,
}

EXIT_NAMES = {
    EXIT_OK: "ok",
    EXIT_UNEXPECTED: "unexpected",
    EXIT_USAGE: "usage_error",
    EXIT_CONFIG: "config_error",
    EXIT_API: "api_error",
    EXIT_NETWORK: "network_error",
}


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="output format (default: json)",
    )
    common.add_argument("--api-base", default=None, help=f"API base URL (env: {API_BASE_ENV})")
    common.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("DEEPSEEK_TIMEOUT", DEFAULT_TIMEOUT)),
        help="per-request timeout in seconds (default: %(default)s)",
    )
    common.add_argument(
        "--retries",
        type=int,
        default=int(os.getenv("DEEPSEEK_RETRIES", DEFAULT_RETRIES)),
        help="retries on 429/5xx/timeout (default: %(default)s)",
    )
    common.add_argument(
        "--raw",
        action="store_true",
        help="print the untouched API response (implies --format json)",
    )
    common.add_argument(
        "--unescape",
        action="store_true",
        help="strip markdown backslash-escapes from summary/content (cleaner prose)",
    )
    common.add_argument(
        "--env-file",
        default=None,
        help="read the API key from this .env file instead of auto-discovering",
    )
    common.add_argument(
        "--no-env-file",
        action="store_true",
        help="do not read key from .env files (env/key-file/command sources only)",
    )
    common.add_argument(
        "--max-chars",
        type=int,
        default=int(os.getenv("DEEPSEEK_MAX_CHARS", DEFAULT_MAX_CHARS)),
        help="cap summary/content per field, 0 = unlimited (default: %(default)s)",
    )

    parser = argparse.ArgumentParser(
        prog="deepseek-web",
        description="Search and fetch the web through DeepSeek's tool API.",
        epilog="Exit codes: 0 ok, 2 usage, 3 config, 4 api, 5 network.",
    )
    parser.add_argument("--version", action="version", version=f"deepseek-web {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    search = subparsers.add_parser(
        "search", parents=[common], help="search the web and return ranked results"
    )
    search.add_argument("query", help="what to search for (<= 128 chars)")
    search.add_argument(
        "--count", "-n", default=5, type=int, help="number of results, 1-50 (default: 5)"
    )
    search.add_argument(
        "--ori-question",
        default=None,
        help="the user's original question, for query rewriting context",
    )
    search.add_argument(
        "--localization",
        default="",
        help="locale hint, e.g. en-US (optional)",
    )
    search.add_argument(
        "--need-content",
        action="store_true",
        help="ask the API for page content for every result",
    )

    fetch = subparsers.add_parser(
        "fetch", parents=[common], help="fetch one URL and extract readable content"
    )
    fetch.add_argument("url", help="http(s) URL to fetch (<= 8192 chars)")

    subparsers.add_parser(
        "doctor",
        parents=[common],
        help="report local readiness without touching the network",
    )

    key = subparsers.add_parser(
        "key",
        help="inspect or provision the API key (status, set, clear)",
    )
    key_sub = key.add_subparsers(dest="key_action", metavar="ACTION")
    key_sub.add_parser("status", parents=[common], help="show where the key would come from")
    key_set = key_sub.add_parser(
        "set", parents=[common], help="store a key in .env (reads stdin by default)"
    )
    key_set.add_argument("--value", default=None, help="key value (prefer stdin; argv leaks to ps)")
    key_set.add_argument(
        "--path",
        default=None,
        help="target .env file (default: ./.env)",
    )
    key_clear = key_sub.add_parser("clear", parents=[common], help="remove the key from .env")
    key_clear.add_argument("--path", default=None, help="target .env file (default: ./.env)")
    return parser


# -- rendering -----------------------------------------------------------


def render_search(payload: Dict[str, Any], results: List[SearchResult], as_json: bool) -> str:
    if as_json:
        return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
    if not results:
        return f"No results for {payload.get('query', '')!r}."
    lines = [f"query: {payload.get('query', '')}  results: {len(results)}"]
    for index, result in enumerate(results, 1):
        lines.append("")
        lines.append(f"{index}. {result.title or '(no title)'}")
        lines.append(f"   url: {result.url or '(no url)'}")
        if result.site_name:
            lines.append(f"   site: {result.site_name}")
        if result.date:
            lines.append(f"   date: {result.date}")
        if result.rerank_score is not None:
            authority = "n/a" if result.authority is None else result.authority
            lines.append(f"   score: {result.rerank_score:.3f}  authority: {authority}")
        if result.summary:
            lines.append(f"   summary: {result.summary}")
        if result.content:
            preview = " ".join(result.content.split())[:200]
            lines.append(f"   content: {preview}...")
    return "\n".join(lines)


def render_fetch(payload: Dict[str, Any], page: FetchedPage, as_json: bool) -> str:
    if as_json:
        return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
    header = f"{page.title or '(no title)'}\n{page.url}\n"
    return f"{header}\n{page.content}"


def render_error(exc: DeepSeekError, as_json: bool) -> str:
    code = EXIT_CODES.get(type(exc), EXIT_UNEXPECTED)
    if as_json:
        return json.dumps(
            {
                "error": {
                    "type": EXIT_NAMES[code],
                    "message": str(exc),
                    "status_code": getattr(exc, "status_code", None),
                }
            },
            ensure_ascii=False,
        )
    return f"error: {exc}"


# -- commands ------------------------------------------------------------


def _client_from_args(args: argparse.Namespace) -> Client:
    return Client(
        api_base=args.api_base,
        timeout=args.timeout,
        retries=args.retries,
        env_file=getattr(args, "env_file", None),
        use_env_files=not getattr(args, "no_env_file", False),
    )


def run_search(args: argparse.Namespace) -> int:
    max_chars = validate_max_chars(args.max_chars)
    client = _client_from_args(args)
    raw = client.search_raw(
        query=args.query,
        count=args.count,
        ori_question=args.ori_question,
        localization=args.localization,
        need_content=args.need_content,
    )
    as_json = args.format == "json" or args.raw
    if args.raw:
        print(json.dumps(raw, indent=2, ensure_ascii=False))
        return EXIT_OK

    from .models import results_from_payload

    results = results_from_payload(raw)
    if args.unescape:
        results = [
            replace(
                result,
                summary=strip_markdown_escapes(result.summary) or "",
                content=strip_markdown_escapes(result.content) or "",
            )
            for result in results
        ]
    if max_chars:
        results = [
            replace(
                result,
                summary=truncate_text(result.summary, max_chars),
                content=truncate_text(result.content, max_chars),
            )
            for result in results
        ]
    payload: Dict[str, Any] = {
        "query": args.query.strip(),
        "count": args.count,
        "results": [result.to_dict() for result in results],
    }
    print(render_search(payload, results, as_json))
    return EXIT_OK


def run_fetch(args: argparse.Namespace) -> int:
    max_chars = validate_max_chars(args.max_chars)
    client = _client_from_args(args)
    raw = client.fetch_raw(args.url)
    if args.raw:
        print(json.dumps(raw, indent=2, ensure_ascii=False))
        return EXIT_OK

    page = FetchedPage.from_payload(raw, url=args.url)
    if args.unescape:
        page = replace(page, content=strip_markdown_escapes(page.content) or "")
    if max_chars:
        page = replace(page, content=truncate_text(page.content, max_chars))
    payload = page.to_dict()
    print(render_fetch(payload, page, args.format == "json"))
    return EXIT_OK


def run_doctor(args: argparse.Namespace) -> int:
    try:
        api_base = resolve_api_base(args.api_base)
        base_error = None
    except ConfigError as exc:
        api_base = args.api_base or DEFAULT_API_BASE
        base_error = str(exc)

    resolution = None
    key_error = None
    try:
        resolution = resolve_key(
            env_file=args.env_file, use_env_files=not args.no_env_file
        )
    except ConfigError as exc:
        key_error = str(exc).splitlines()[0]

    report: Dict[str, Any] = {
        "version": __version__,
        "python": platform.python_version(),
        "executable": sys.executable,
        "api_base": api_base,
        "api_key_env": ENV_VAR,
        "api_key_set": resolution is not None,
        "api_key_hint": resolution.masked if resolution else None,
        "api_key_source": resolution.describe() if resolution else None,
        "timeout": args.timeout,
        "retries": args.retries,
        "ready": resolution is not None and base_error is None,
        "problems": [],
    }
    if resolution is None:
        report["problems"].append(key_error)
    if base_error:
        report["problems"].append(base_error)

    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"deepseek-web {report['version']} on Python {report['python']}")
        print(f"api base : {report['api_base']}")
        if resolution:
            print(f"api key  : {resolution.masked} from {resolution.source} ({resolution.origin})")
        else:
            print("api key  : missing")
        print(f"ready    : {'yes' if report['ready'] else 'no'}")
        for problem in report["problems"]:
            print(f"  - {problem}")
    return EXIT_OK


def run_key_status(args: argparse.Namespace) -> int:
    try:
        resolution = resolve_key(
            env_file=args.env_file, use_env_files=not args.no_env_file
        )
        status: Dict[str, Any] = {
            "ready": True,
            "api_key_set": True,
            "api_key_hint": resolution.masked,
            "source": resolution.describe(),
        }
    except ConfigError as exc:
        status = {
            "ready": False,
            "api_key_set": False,
            "api_key_hint": None,
            "source": None,
            "error": str(exc),
        }

    status["env_files"] = [
        {"path": str(path), "exists": path.exists()}
        for path in (
            [Path(args.env_file).expanduser()]
            if args.env_file
            else candidate_env_files()
        )
    ]
    status["zeroclaw"] = diagnose_zeroclaw()

    if args.format == "json":
        print(json.dumps(status, indent=2, ensure_ascii=False))
    else:
        if status["api_key_set"]:
            source = status["source"]
            print(f"key: {status['api_key_hint']} from {source['source']} ({source['origin']})")
        else:
            print("key: missing")
        for entry in status["env_files"]:
            print(f"  .env {entry['path']} {'[present]' if entry['exists'] else ''}".rstrip())
        note = status["zeroclaw"].get("note")
        if note:
            print(f"  note: {note}")
    return EXIT_OK


def run_key_set(args: argparse.Namespace) -> int:
    if args.value is not None:
        # Explicitly passed --value: never fall through to stdin, or a blank
        # value would look like a hang when stdin is an interactive terminal.
        value = args.value.strip()
        if not value:
            raise ValidationError("refusing to store an empty key")
    else:
        if sys.stdin is None or sys.stdin.isatty():
            raise ValidationError(
                "no key provided; pipe it on stdin or pass --value"
            )
        try:
            value = sys.stdin.read().strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise ConfigError(f"could not read key from stdin: {exc}") from exc
    if not value:
        raise ValidationError("refusing to store an empty key")
    if any(ch.isspace() for ch in value):
        raise ValidationError("API key must not contain whitespace")

    target = Path(args.path).expanduser() if args.path else Path.cwd() / ".env"
    written = write_env_file(target, {ENV_VAR: value})
    payload = {
        "stored": True,
        "path": str(written),
        "mode": oct(written.stat().st_mode & 0o777),
        "api_key_hint": f"****{value[-4:]}" if len(value) >= 8 else "****",
        "gitignored": _is_gitignored(written),
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"stored key {payload['api_key_hint']} in {payload['path']} ({payload['mode']})")
        if not payload["gitignored"]:
            print("  warning: this path is not covered by .gitignore")
    return EXIT_OK


def run_key_clear(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser() if args.path else Path.cwd() / ".env"
    removed = remove_env_key(target)
    payload = {"removed": removed, "path": str(target)}
    if args.format == "json":
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"{'removed' if removed else 'no key found in'} {target}")
    return EXIT_OK


def _is_gitignored(path: Path) -> bool:
    """Cheap check: is this .env covered by a .gitignore in this or a parent dir?"""
    name = path.name
    for directory in [path.parent, *list(path.parent.parents)[:6]]:
        ignore = directory / ".gitignore"
        if not ignore.exists():
            continue
        try:
            lines = ignore.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            entry = line.strip()
            if entry in (name, f"{name}*", f"*.env", "*"):
                return True
    return False


def run_key(args: argparse.Namespace) -> int:
    handlers = {
        "status": run_key_status,
        "set": run_key_set,
        "clear": run_key_clear,
    }
    if not getattr(args, "key_action", None):
        raise ValidationError("key requires an action: status, set, or clear")
    return handlers[args.key_action](args)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_USAGE

    handlers = {
        "search": run_search,
        "fetch": run_fetch,
        "doctor": run_doctor,
        "key": run_key,
    }
    handler = handlers[args.command]
    as_json = getattr(args, "format", "json") == "json" or getattr(args, "raw", False)

    try:
        return handler(args)
    except DeepSeekError as exc:
        print(render_error(exc, as_json), file=sys.stderr)
        return EXIT_CODES.get(type(exc), EXIT_UNEXPECTED)
    except KeyboardInterrupt:
        print(render_error(ValidationError("interrupted"), as_json), file=sys.stderr)
        return 130
    except BrokenPipeError:  # downstream consumer closed the pipe
        return EXIT_OK
    except Exception as exc:  # last resort: never traceback at an agent
        print(
            render_error(APIError(f"unexpected failure: {exc}"), as_json),
            file=sys.stderr,
        )
        return EXIT_UNEXPECTED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
