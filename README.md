# deepseek-web

Search and fetch the web through DeepSeek's server-side tool API. One CLI, stdlib-only Python,
JSON in / JSON out. Built to be **downloaded and wired into an agent as a subprocess tool** —
not run as an MCP server.

```
$ deepseek-web search "why is the sky blue" -n 3
$ deepseek-web fetch https://example.com
$ deepseek-web doctor
```

## For agents

This repo is a **portable skill**, not just a CLI. If you are an agent being asked to set it up,
read [`skills/deepseek-web/SKILL.md`](skills/deepseek-web/SKILL.md) and follow it — it covers
locating the command, verifying the key, invocation, and failure handling. The folder format is
the open Agent Skills layout (`SKILL.md` + `references/`), so it drops into whatever skill
mechanism your runtime uses. No MCP server, no registry, no package install required.

Humans can keep reading below.

## Why not MCP

MCP is a good fit when you need a long-lived server, shared state, or capability negotiation
between many clients. This tool needs none of that. It is a single request/response call with a
flat contract, so the cheapest integration wins:

- **No daemon** — the process starts, does one thing, exits.
- **No protocol layer** — stdin/stdout is already the universal interface.
- **No SDK** — `subprocess.run([...], capture_output=True)` works in every runtime.
- **No dependencies** — drops onto a box with Python 3.9 and nothing else.

If your agent can call a shell, it can call this.

## Install

```bash
# Option A: zero install, run from the checkout
python3 -m deepseek_web search "rust async runtime" -n 5

# Option B: install as a console script
pip install .

# Option C: isolated install (recommended for a shared box)
pipx install .
```

Verify without spending a request:

```bash
deepseek-web doctor --format text
```

## Auth

An API key is required. The tool never takes it as a positional argument (so it cannot land in
`ps` output or shell history) and never logs it. It resolves the key from the first non-empty
source in this order:

| # | Source | How |
| :--- | :--- | :--- |
| 1 | Environment | `DEEPSEEK_API_KEY` |
| 2 | Key file | `--env-file PATH`, or `DEEPSEEK_API_KEY_FILE=/path/to/key` |
| 3 | Command | `DEEPSEEK_API_KEY_CMD="pass show deepseek"` (stdout is the key) |
| 4 | `.env` discovery | walking up from `cwd`, then `~/.config/deepseek-web/.env`, then `~/.env` |
| 5 | Secret mount | `/run/secrets/deepseek_api_key` |

Empty values count as missing. That matters in containers, where compose commonly declares
`DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-}` and an unset host variable arrives as `""`.

**No .env to write by hand.** Provision once, from stdin, and the tool stores it at `./.env`
with mode `0600`:

```bash
echo "$KEY" | deepseek-web key set        # or: deepseek-web key set --value "$KEY"
deepseek-web key status                   # where would the key come from?
deepseek-web key clear                    # remove it again
```

`key set` merges into an existing `.env` instead of overwriting it, writes atomically, and
chmods the file. `.env` is gitignored in this repo.

> Some runtimes store provider keys **encrypted at rest** (`enc2:`, `gpg:`, `sops:`, `age:`,
> `vault:` ...). Those blobs are decrypted by whichever tool owns them and are not usable as a
> credential here — sending one always gets a 401. The tool refuses them up front: `key status`
> flags it, `key set` rejects it, and a call exits `3` instead of wasting a request.

Optional environment overrides:

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `DEEPSEEK_API_BASE` | `https://api.deepseek.com/v1/tools` | Point at a mirror or proxy |
| `DEEPSEEK_TIMEOUT` | `30` | Per-request timeout, seconds |
| `DEEPSEEK_RETRIES` | `2` | Retries on 429/5xx/timeout |

### Containers: get the key in without a .env

If the key is already in the container environment (compose `environment:` or `env_file:`),
the remaining gap is usually that the agent runtime hands its subprocesses a **filtered**
environment. Many runtimes expose an allowlist for exactly this; others inherit the container
environment untouched. Check with one command inside the agent's shell:

```bash
deepseek-web doctor        # "ready: yes" means the key reached this process
```

If it does not, three routes that never involve hand-editing a config file:

1. **Allowlist the variable** in whatever the runtime calls its shell/exec environment policy.
2. **Mount a file** read-only and point at it:

   ```yaml
   volumes:
     - ./.env:/app/.env:ro
   environment:
     - DEEPSEEK_API_KEY_FILE=/app/.env
   ```

3. **Read it from a secret manager** at call time:

   ```bash
   export DEEPSEEK_API_KEY_CMD="pass show deepseek"
   ```

Either way the user never writes a key into a config by hand — it arrives with the container.


## Commands

### `search`

```bash
deepseek-web search QUERY [--count N] [--ori-question Q] [--localization en-US] [--need-content]
```

| Flag | Default | Notes |
| :--- | :--- | :--- |
| `--count`, `-n` | `5` | 1–50 |
| `--ori-question` | none | The user's original question; improves query rewriting |
| `--localization` | none | Locale hint such as `en-US` |
| `--need-content` | off | Ask for page content on every result (costlier, larger) |

Output:

```json
{
  "query": "why is the sky blue",
  "count": 3,
  "results": [
    {
      "title": "Rayleigh scattering",
      "url": "https://example.com/sky",
      "summary": "Shorter wavelengths scatter more strongly.",
      "content": "",
      "site_name": "Example",
      "date": "2026-01-02",
      "rerank_score": 0.87,
      "authority": 0.42
    }
  ]
}
```

### `fetch`

```bash
deepseek-web fetch URL
```

Output:

```json
{
  "url": "https://example.com",
  "title": "Example Domain",
  "content": "This domain is for use in illustrative examples..."
}
```

### `doctor`

Reports version, Python, resolved API base, whether the key is present (masked, with its
source), and readiness. Never touches the network, never prints the key.

### `key`

```bash
deepseek-web key status          # resolution chain + zero-claw config diagnosis
deepseek-web key set             # read key from stdin, write ./.env (0600)
deepseek-web key clear           # remove it from ./.env
```

`key status` also lists the `.env` files it looked at, and reports when the resolved value is
a wrapped secret rather than a plaintext key.

### Common flags

| Flag | Effect |
| :--- | :--- |
| `--format json\|text` | `json` (default) for agents, `text` for humans |
| `--raw` | Print the untouched API response — use this to verify field names |
| `--unescape` | Strip markdown backslash-escapes from `summary` / `content` |
| `--max-chars N` | Cap `summary` / `content` per field (default `8000`, `0` = unlimited) |
| `--api-base URL` | Override the endpoint |
| `--timeout SECONDS` | Override the timeout |
| `--retries N` | Override the retry count |

A single `--need-content` result can run to tens of thousands of characters. `--max-chars` keeps
that from becoming someone's context budget, and truncation is always marked with
`…[truncated N chars]` so a clipped page is never mistaken for a complete one. `--raw` bypasses
the cap entirely.

## Response schema (verified)

Confirmed against live authenticated calls on 2026-10-19:

`search` — `{"results": [{...}]}`. Each result:

| Field | Type | Notes |
| :--- | :--- | :--- |
| `title` | string | |
| `url` | string | |
| `summary` | string | markdown; often long, can contain `\`-escaped punctuation |
| `content` | string | usually `""` unless `--need-content` is passed |
| `site_name` | string | e.g. `Fermilab (.gov)` |
| `date` | string | ISO 8601 with offset |
| `rerank_score` | float | higher is better; typically 2.0–2.4 |
| `authority` | number | site authority, commonly `4.0` |
| `snippet` | string | short excerpt, preserved under `extra` |
| `site_icon` | string | CDN URL, preserved under `extra` |

`fetch` — `{"url", "title", "content"}`. `content` is extracted markdown and arrives with
punctuation backslash-escaped (`Why is the sky blue\?`); pass `--unescape` if the consumer
wants plain prose.

## Exit codes

| Code | Meaning | What the caller should do |
| :--- | :--- | :--- |
| `0` | Success | Parse stdout |
| `1` | Unexpected internal failure | Log it; do not retry blindly |
| `2` | Usage / validation error | Fix the arguments |
| `3` | Configuration error (missing key) | Prompt for credentials |
| `4` | API error (4xx/5xx) | Inspect `status_code`; 401 = bad key |
| `5` | Network error | Retry with backoff |

Errors are written to **stderr** in the same format as successful output:

```json
{"error": {"type": "api_error", "message": "API error 401: Authentication Fails", "status_code": 401}}
```

stdout stays clean on failure. That is deliberate: an agent can parse stdout unconditionally.

## Wiring it into an agent

```python
import json
import subprocess


def deepseek_search(query: str, count: int = 5) -> dict:
    proc = subprocess.run(
        ["deepseek-web", "search", query, "--count", str(count)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"search failed ({proc.returncode}): {proc.stderr.strip()}")
    return json.loads(proc.stdout)
```

`examples/tool-descriptor.json` is a ready-made, MCP-free descriptor you can hand to an agent
runtime that accepts JSON tool definitions. `examples/agent_integration.sh` is a shell-only
variant for runtimes that only speak bash.

## Python library

```python
import deepseek_web

results = deepseek_web.search("rust async runtime", count=5)
print(results[0].title, results[0].rerank_score)

page = deepseek_web.fetch("https://example.com")
print(page.title, len(page.content))
```

Typed models (`SearchResult`, `FetchedPage`) degrade gracefully: fields that are missing or of an
unexpected type become `None` / `""` rather than raising, so a schema change upstream does not
take the agent down.

## Development

```bash
python3 -m unittest discover -s tests -t . -v
```

109 tests, no network, no key required. Everything HTTP is mocked.

## Status and limitations

- Response schema confirmed against live authenticated calls on 2026-10-19. If DeepSeek changes
  a field name, parsing degrades to `null`/`""` rather than crashing; run `--raw` to see what
  actually came back.
- `fetch` handles one URL per invocation. Batch fetching is intentionally left to the caller.
- Synchronous only. Parallelism belongs in the caller's worker pool, not inside a one-shot CLI.
- Billing is on DeepSeek's side: search and fetch are metered per successful request.

## License

MIT.
