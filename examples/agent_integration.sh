#!/usr/bin/env bash
# Minimal shell integration for agent runtimes that only speak bash.
# No jq required. Requires DEEPSEEK_API_KEY in the environment.

set -euo pipefail

DEEPSEEK_WEB_BIN="${DEEPSEEK_WEB_BIN:-deepseek-web}"

deepseek_web() {
  local action="$1"; shift
  "$DEEPSEEK_WEB_BIN" "$action" "$@"
}

# deepseek_search "query" [count] -> JSON on stdout, non-zero on failure
deepseek_search() {
  local query="$1" count="${2:-5}"
  deepseek_web search "$query" --count "$count"
}

# deepseek_fetch "https://..." -> JSON on stdout, non-zero on failure
deepseek_fetch() {
  local url="$1"
  deepseek_web fetch "$url"
}

# deepseek_ready -> "yes" / "no"; never calls the network
deepseek_ready() {
  local out
  out="$(deepseek_web doctor --format json 2>/dev/null || true)"
  case "$out" in
    *'"ready": true'*) echo "yes" ;;
    *) echo "no" ;;
  esac
}

# Retry helper: only network failures (exit 5) are retried.
deepseek_search_with_retry() {
  local query="$1" count="${2:-5}" attempt=1 max=3 code=0
  while true; do
    if deepseek_web search "$query" --count "$count"; then
      return 0
    else
      code=$?
    fi
    if [ "$code" -ne 5 ] || [ "$attempt" -ge "$max" ]; then
      return "$code"
    fi
    attempt=$((attempt + 1))
    sleep $((attempt * 2))
  done
}
