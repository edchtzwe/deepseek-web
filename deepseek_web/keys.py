"""Credential discovery.

The goal is zero manual setup: the tool looks for a key in every place a
containerised agent realistically already has one, in a fixed order, and
reports which source won.

Resolution order (first non-empty wins):

1. explicit argument (library callers only)
2. ``DEEPSEEK_API_KEY`` environment variable
3. ``DEEPSEEK_API_KEY_FILE`` - a bare key, or a file carrying an assignment
4. ``DEEPSEEK_API_KEY_CMD`` - shell command whose stdout is the key
   (``pass show deepseek``, ``op read op://...``, ``docker exec ...``)
5. ``.env`` files: ``--env-file`` / ``DEEPSEEK_WEB_ENV_FILE`` when given, else
   discovered walking up from the working directory, then
   ``~/.config/deepseek-web/.env`` and ``~/.env``
6. well-known secret mounts (``/run/secrets/...``)

Empty values are treated as missing, which matters because compose files
commonly declare ``DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-}`` - an unset
host variable arrives as an empty string, not as "absent".
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .errors import ConfigError, EncryptedKeyError

ENV_VAR = "DEEPSEEK_API_KEY"
KEY_FILE_ENV = "DEEPSEEK_API_KEY_FILE"
KEY_CMD_ENV = "DEEPSEEK_API_KEY_CMD"
ENV_FILE_VAR = "DEEPSEEK_WEB_ENV_FILE"
DEFAULT_ENV_FILENAME = ".env"

SECRET_PATHS: Tuple[str, ...] = (
    "/run/secrets/deepseek_api_key",
    "/run/secrets/DEEPSEEK_API_KEY",
    "/run/secrets/deepseek-web",
)

MAX_PARENT_WALK = 8
CMD_TIMEOUT = 15.0

_ASSIGNMENT = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


# -- resolution ----------------------------------------------------------


@dataclass(frozen=True)
class KeyResolution:
    """Where the key came from. Never carries the raw key into a log."""

    key: str
    source: str
    origin: str

    @property
    def masked(self) -> str:
        return f"****{self.key[-4:]}" if len(self.key) >= 8 else "****"

    def describe(self) -> Dict[str, object]:
        return {"source": self.source, "origin": self.origin, "masked": self.masked}


def candidate_env_files(cwd: Optional[Path] = None) -> List[Path]:
    """Every ``.env`` path worth reading, in priority order, deduplicated."""
    paths: List[Path] = []

    explicit = os.getenv(ENV_FILE_VAR)
    if explicit:
        paths.append(Path(explicit).expanduser())

    start = (cwd or Path.cwd()).resolve()
    for directory in [start, *list(start.parents)[:MAX_PARENT_WALK]]:
        paths.append(directory / DEFAULT_ENV_FILENAME)

    home = Path.home()
    paths.extend(
        [
            home / ".config" / "deepseek-web" / DEFAULT_ENV_FILENAME,
            home / f"{DEFAULT_ENV_FILENAME}",
        ]
    )

    seen: set = set()
    unique: List[Path] = []
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def parse_dotenv(text: str) -> Dict[str, str]:
    """Parse a minimal ``KEY=VALUE`` file. No interpolation, no surprises."""
    values: Dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.lstrip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGNMENT.match(line)
        if not match:
            continue
        name, value = match.group(1), match.group(2).strip()
        quote = value[:1] if value[:1] in ("'", '"') else ""
        if quote and len(value) >= 2 and value[-1] == quote:
            value = value[1:-1]
            if quote == '"':
                value = value.replace('\\"', '"')
        else:
            value = _strip_inline_comment(value)
        values[name] = value
    return values


def _strip_inline_comment(value: str) -> str:
    if " #" in value:
        return value.split(" #", 1)[0].rstrip()
    if "\t#" in value:
        return value.split("\t#", 1)[0].rstrip()
    return value


def read_env_file(path: Path, name: str = ENV_VAR) -> Optional[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeError):
        return None
    value = parse_dotenv(text).get(name, "").strip()
    return value or None


def read_key_file(path: Path) -> Optional[str]:
    """A key file is either a bare key or a ``KEY=VALUE`` file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeError):
        return None
    parsed = parse_dotenv(text)
    if ENV_VAR in parsed:
        return parsed[ENV_VAR].strip() or None
    for raw_line in text.splitlines():
        line = raw_line.lstrip()
        if not line or line.startswith("#"):
            continue
        return line.strip()
    return None


def read_key_command(command: str) -> Optional[str]:
    try:
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=CMD_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConfigError(f"{KEY_CMD_ENV} command failed: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise ConfigError(
            f"{KEY_CMD_ENV} exited {completed.returncode}{suffix}"
        )
    for line in reversed(completed.stdout.splitlines()):
        if line.strip():
            return line.strip()
    return None


def _accept(value: str, source: str, origin: str) -> KeyResolution:
    """Build a resolution, refusing wrapped secrets before they are sent."""
    if looks_encrypted(value):
        raise EncryptedKeyError(encrypted_key_message(value))
    return KeyResolution(value, source, origin)


def resolve_key(
    explicit: Optional[str] = None,
    key_file: Optional[Path] = None,
    env_file: Optional[Path] = None,
    use_env_files: bool = True,
    cwd: Optional[Path] = None,
) -> KeyResolution:
    """Find a key or raise :class:`ConfigError` with the searched paths."""
    if explicit and explicit.strip():
        return _accept(explicit.strip(), "argument", "api_key")

    env_value = (os.getenv(ENV_VAR) or "").strip()
    if env_value:
        return _accept(env_value, "env", ENV_VAR)

    file_candidates: List[Path] = []
    if key_file is not None:
        file_candidates.append(Path(key_file).expanduser())
    elif os.getenv(KEY_FILE_ENV):
        file_candidates.append(Path(os.environ[KEY_FILE_ENV]).expanduser())
    for path in file_candidates:
        value = read_key_file(path)
        if value:
            return _accept(value, "file", str(path))

    command = (os.getenv(KEY_CMD_ENV) or "").strip()
    if command:
        value = read_key_command(command)
        if value:
            return _accept(value, "command", KEY_CMD_ENV)

    if use_env_files:
        candidates = [Path(env_file).expanduser()] if env_file else candidate_env_files(cwd)
        for path in candidates:
            value = read_env_file(path)
            if value:
                return _accept(value, "dotenv", str(path))

    for secret in SECRET_PATHS:
        value = read_key_file(Path(secret))
        if value:
            return _accept(value, "secret", secret)

    raise ConfigError(_missing_key_message(cwd, env_file, use_env_files))


def _missing_key_message(
    cwd: Optional[Path], env_file: Optional[Path], use_env_files: bool
) -> str:
    lines = [
        f"No DeepSeek API key found. Set {ENV_VAR} in the environment.",
        f"Alternatives: {KEY_FILE_ENV} (a file holding only the key) or "
        f"{KEY_CMD_ENV} (a command whose stdout is the key).",
        "This tool never stores or writes a key; provisioning is the user's job.",
        "Then verify with: deepseek-web doctor",
    ]
    if use_env_files:
        paths = [Path(env_file).expanduser()] if env_file else candidate_env_files(cwd)
        existing = [str(path) for path in paths if path.exists()]
        lines.append(
            "Checked .env files: " + (", ".join(existing) if existing else "none found")
        )
    lines.append(f"Secret mounts checked: {', '.join(SECRET_PATHS)}")
    return "\n".join(lines)


# -- sanity checks -------------------------------------------------------

#: Wrapped secrets: ``enc2:...``, ``gpg:...``, ``sops:...`` and friends. A
#: colon is required so an ordinary token that merely starts with these
#: letters is not mistaken for a wrapper.
ENCRYPTED_WRAPPER = re.compile(
    r"^(?:enc\d*|encrypted|gpg|age|vault|sops|sealed|base64):", re.IGNORECASE
)


def looks_encrypted(value: str) -> bool:
    """True when ``value`` is a wrapped secret rather than a plaintext key.

    Nothing is decrypted and no file is read: this is a prefix test on a
    value the caller already has. It exists so a pasted ciphertext blob
    fails with an explanation instead of a confusing 401 from the API.
    """
    if not value:
        return False
    return ENCRYPTED_WRAPPER.match(value.strip()) is not None


def encrypted_key_message(value: str) -> str:
    """Explain a wrapped secret without echoing any part of it."""
    scheme = value.strip().split(":", 1)[0]
    return (
        f"The value found is wrapped secret data (prefix '{scheme}:'), not a plaintext API key. "
        "Encrypted-at-rest values are decrypted by whichever tool owns them and "
        f"cannot be used as a credential here. Supply the raw key via {ENV_VAR}, "
        f"{KEY_FILE_ENV}, or {KEY_CMD_ENV}."
    )
