---
name: deepseek-web
description: Search the web and extract readable page text through DeepSeek's search and fetch API. Use when a task needs current sources with dates and authority scores, ranked results for a query, or clean prose from a specific URL instead of raw HTML. Returns a single JSON object on stdout with documented exit codes; no MCP server, no daemon, no background process, no SDK.
license: MIT
---

# deepseek-web

One subprocess call in, one JSON object out. Stdlib-only Python 3.9+. Nothing to install if you
already have this repo.

Use it for: a question that needs current facts, a claim worth a source, a list of ranked pages
for a query, or the readable text of one URL.

Do not use it for: local files, private data, or anything you can answer from what you already
know.

## 1. Locate the command

Try in this order, stop at the first that works:

1. **On `PATH`** — `deepseek-web --version`
2. **From the repo checkout** — `python3 -m deepseek_web --version`, run from the repo root. Find
   that root by trying, in order:
   - `$DEEPSEEK_WEB_HOME`, if set
   - the directory **two levels above this file** (correct when you are reading this inside the
     repo, at `skills/deepseek-web/SKILL.md`)
   - a `deepseek-web` directory beside the directory holding this skill (correct for an installed
     copy)

   Before trusting a candidate, confirm it contains `deepseek_web/__init__.py`. A directory that
   lacks it is not the repo.
3. **Repo missing** — clone it, then use step 2.

Below, `deepseek-web` means whichever form worked. Everything else is identical.

## 2. Verify before the first call

```bash
deepseek-web doctor
```

- `"ready": true` → proceed.
- `"api_key_set": false` → the key is missing. **Stop and hand it back.** This tool only
  reads a key; it never stores one, and you must not offer to set one up.

  Say plainly that the user needs a DeepSeek API key and point them at the three ways to
  supply one:

  ```bash
  export DEEPSEEK_API_KEY=...                        # environment, preferred
  export DEEPSEEK_API_KEY_FILE=/path/to/key          # file holding only the key
  export DEEPSEEK_API_KEY_CMD="pass show deepseek"   # command, stdout is the key
  ```

  If the user is on a hosted agent that already integrates DeepSeek as a provider, the key
  likely exists there under a different variable name — that platform's own setup owns it.
  Do not paper over the gap by writing a `.env` "just to get it working". Never ask the user
  to paste a key into chat, and never echo one back. `doctor` prints a masked hint only.

`doctor` never touches the network, so it costs nothing.

## 3. Commands

```bash
deepseek-web search "QUERY" --count 5
deepseek-web search "QUERY" --count 3 --ori-question "the user's full question"
deepseek-web fetch "https://example.com/page"
```

Useful flags:

| Flag | When |
| :--- | :--- |
| `--count N` / `-n N` | 1–50. Default 5. Use 3 for narrow questions, 8+ only for genuine breadth. |
| `--ori-question Q` | Pass the user's original wording when the search query is a rewrite; improves ranking. |
| `--unescape` | Pass when the text will be read as prose. `fetch` and long summaries arrive with markdown backslashes (`blue\?`); this strips them. |
| `--need-content` | Only when summaries are not enough. Much larger payload, per-result content. |
| `--max-chars N` | Per-field cap on `summary`/`content`. Default 8000. `0` disables it. |
| `--format text` | Human-readable. Do not use when you need to parse. |
| `--raw` | Untouched API payload. Only for debugging a schema surprise. |

Keep `--count` small unless the task needs breadth. Every result is tokens you pay for on every
later turn.

## 4. Output

`search`:

```json
{"query": "...", "count": 3, "results": [
  {"title": "...", "url": "...", "summary": "...", "content": "",
   "site_name": "...", "date": "2026-01-02", "rerank_score": 2.09, "authority": 4.0}
]}
```

`fetch`:

```json
{"url": "...", "title": "...", "content": "..."}
```

Always present: the keys above. `content` is `""` unless `--need-content` (search) or a `fetch`.
Numeric fields may be `null`. Truncated text ends with `…[truncated N chars]` — treat that as
"there was more", and raise `--max-chars` only if you actually need the rest.

Full schema, `extra` passthrough, and exit-code semantics: `references/contract.md`.

## 5. Exit codes and what to do

| Code | Meaning | Action |
| :--- | :--- | :--- |
| `0` | ok | Parse stdout |
| `2` | bad arguments | Fix the call. Do not retry unchanged. |
| `3` | missing or unusable key | Ask the user. Do not loop. |
| `4` | API error | Read `status_code`. Never retry `400`/`401`. |
| `5` | network error | Retry up to 3 times with backoff. |
| `1` | unexpected | Report it. Do not retry blindly. |

Errors go to **stderr** as one JSON object:

```json
{"error": {"type": "api_error", "message": "...", "status_code": 401}}
```

stdout stays empty on failure, so `json.loads(stdout)` is always safe when the exit code is `0`.

If a call fails, say so. Never present invented results as if they came from this tool.

## 6. Installing this skill

This is a portable skill folder. Different runtimes load skills from different places; trust
your own conventions:

- If you manage skills with a command, use it and point it at this directory.
- If you load skills from a filesystem directory, copy this folder into it unchanged — the
  directory name must stay `deepseek-web` so it matches `name` in the frontmatter.
- If you have neither, ask the user where skills belong.

Do not scatter files into multiple directories and do not rename the folder. If you cannot
determine the right location, stop and ask.

The skill directory is self-contained apart from the CLI itself. The code lives in the repo this
folder came from; do not duplicate it into the skill directory.
