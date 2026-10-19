# deepseek-web output contract

Everything here is verified against live authenticated calls on 2026-10-19. If reality disagrees,
`--raw` shows the untouched payload and this file is wrong — trust `--raw`.

## Invariants

- stdout carries exactly one JSON object on success. Nothing else, ever.
- stderr carries exactly one JSON object on failure. stdout is empty.
- Exit code is the primary signal; parse JSON second.
- No prompts, no state, no daemon. Every invocation is independent.

## `search` on stdout (exit 0)

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
      "date": "2026-01-02T00:00:00+00:00",
      "rerank_score": 2.086,
      "authority": 4.0
    }
  ]
}
```

| Field | Type | Notes |
| :--- | :--- | :--- |
| `query` | string | The query actually sent, stripped |
| `count` | int | The requested count, not necessarily `len(results)` |
| `results` | array | Empty array when nothing matched — not an error |
| `results[].title` | string | May be `""` |
| `results[].url` | string | Source URL |
| `results[].summary` | string | Markdown; often long; may contain `\`-escaped punctuation |
| `results[].content` | string | `""` unless `--need-content` |
| `results[].site_name` | string | e.g. `Fermilab (.gov)` |
| `results[].date` | string | ISO 8601 with offset, `""` if unknown |
| `results[].rerank_score` | float or null | Higher is better; typically 2.0–2.4 |
| `results[].authority` | float or null | Site authority; commonly 4.0 |
| `results[].extra` | object | Present only when the API sent unmodelled fields |

`extra` currently carries `snippet` (short excerpt) and `site_icon` (CDN URL). Anything DeepSeek
adds later lands here instead of being dropped, so check `extra` before concluding a field is
missing.

## `fetch` on stdout (exit 0)

```json
{"url": "https://example.com", "title": "Example Domain", "content": "This domain is..."}
```

`content` is extracted markdown, not HTML. It arrives with punctuation backslash-escaped
(`Why is the sky blue\?`, `January 23\, 2018`) — pass `--unescape` when the consumer wants prose
rather than markdown. Fenced code blocks and Windows paths are preserved.

## Errors on stderr (exit != 0)

```json
{"error": {"type": "api_error", "message": "API error 401: Authentication Fails", "status_code": 401}}
```

| `type` | Exit | Cause |
| :--- | :--- | :--- |
| `usage_error` | 2 | Bad query, URL, count, or flag |
| `config_error` | 3 | No usable API key, or a malformed override |
| `api_error` | 4 | Upstream 4xx/5xx; `status_code` is set |
| `network_error` | 5 | Timeout, DNS, connection reset |
| `unexpected` | 1 | Bug or unhandled exception |

Retry policy: `5` yes with backoff, `4` only when `status_code` is `429` or `5xx`, never `400`
or `401`, never `2` or `3`.

## `doctor` on stdout (exit 0)

No network access. Reports `version`, `python`, `executable`, `api_base`, `api_key_set`,
`api_key_hint` (masked), `api_key_source`, `timeout`, `retries`, `ready`, and `problems`.

Use `ready` as a single boolean gate before the first real call.

## Key resolution order

First non-empty source wins. An empty string counts as missing, which is why a container with
`DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-}` and an unset host variable behaves as "no key".

1. `DEEPSEEK_API_KEY`
2. `--env-file PATH`, or `DEEPSEEK_API_KEY_FILE`
3. `DEEPSEEK_API_KEY_CMD` (a shell command whose stdout is the key)
4. `.env` found walking up from `cwd`, then `~/.config/deepseek-web/.env`, then `~/.env`
5. `/run/secrets/deepseek_api_key`

A 131-character `enc2:` value copied out of a ZeroClaw `config.toml` is ciphertext, not a
credential. It will always 401. `deepseek-web key status` detects and reports this.

## Environment overrides

| Variable | Default |
| :--- | :--- |
| `DEEPSEEK_API_KEY` | unset |
| `DEEPSEEK_API_BASE` | `https://api.deepseek.com/v1/tools` |
| `DEEPSEEK_TIMEOUT` | `30` seconds |
| `DEEPSEEK_RETRIES` | `2` |
| `DEEPSEEK_MAX_CHARS` | `8000` (`0` = unlimited) |

## Python use (no subprocess)

```python
import deepseek_web

results = deepseek_web.search("rust async runtime", count=5)
page = deepseek_web.fetch("https://example.com")
```

`SearchResult` and `FetchedPage` degrade gracefully: a missing or mistyped field becomes `None`
or `""` rather than raising, so an upstream schema change does not take the caller down.
