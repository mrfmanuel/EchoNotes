#!/usr/bin/env bash
# Resolve commits for the deploy workflows (#25, #26, #27). Prints ONE value on stdout;
# diagnostics go to stderr.
#
# Usage:
#   scripts/resolve-commit.sh ref <sha>          full 40-char SHA of a commit on main
#   scripts/resolve-commit.sh health <base-url>  commit reported by <base-url>/api/health,
#                                                 or "unknown" (unreachable, missing, not a SHA)
#
# `ref` accepts a short or full hex SHA (7-40 chars; branch names and other refs are rejected),
# needs a checkout with history (actions/checkout `fetch-depth: 0`) and fails unless the commit
# is an ancestor of RESOLVE_MAIN_REF (default origin/main): only commits that passed CI on
# main are deployed. `health` retries for RESOLVE_HEALTH_TIMEOUT seconds (default 120, Render
# free instances cold-start) and always exits 0, so callers decide what "unknown" means.
#
# Tests: bash scripts/tests/test_deploy.sh
set -euo pipefail

usage() {
  echo "usage: $0 ref <sha> | $0 health <base-url>" >&2
}

[ "$#" -eq 2 ] && [ -n "$2" ] || { usage; exit 2; }

resolve_ref() {
  local ref main_ref full
  ref="$(printf '%s' "$1" | tr 'A-F' 'a-f')"
  main_ref="${RESOLVE_MAIN_REF:-origin/main}"
  if ! printf '%s' "$ref" | grep -Eq '^[0-9a-f]{7,40}$'; then
    echo "ERROR: ref must be a commit SHA (7-40 hex chars)" >&2
    return 1
  fi
  if ! full="$(git rev-parse --verify --quiet "${ref}^{commit}")"; then
    echo "ERROR: commit $ref not found (ambiguous or not in this repository's history)" >&2
    return 1
  fi
  if ! git merge-base --is-ancestor "$full" "$main_ref" 2>/dev/null; then
    echo "ERROR: commit $full is not on $main_ref; only commits on main are deployed" >&2
    return 1
  fi
  printf '%s\n' "$full"
}

resolve_health() {
  local base_url timeout deadline code body commit py candidate
  base_url="${1%/}"
  timeout="${RESOLVE_HEALTH_TIMEOUT:-120}"
  deadline=$(($(date +%s) + timeout))
  py=""
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
      "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \
        >/dev/null 2>&1; then
      py="$candidate"
      break
    fi
  done
  [ -n "$py" ] || { echo "ERROR: no working python3/python found" >&2; echo unknown; return 0; }

  while :; do
    body="$(curl -sS --max-time 30 -w '\n%{http_code}' "$base_url/api/health" 2>/dev/null)" ||
      body=$'\n000'
    code="${body##*$'\n'}"
    if [ "$code" = "200" ]; then
      commit="$(printf '%s' "${body%$'\n'*}" | "$py" -c '
import json, sys
try:
    data = json.load(sys.stdin)
    print((data.get("commit") or "") if isinstance(data, dict) else "")
except Exception:
    print("")
' 2>/dev/null || true)"
      if printf '%s' "$commit" | grep -Eq '^[0-9a-f]{40}$'; then
        printf '%s\n' "$commit"
      else
        echo "health HTTP 200 but no commit SHA (got '${commit:-missing}')" >&2
        echo unknown
      fi
      return 0
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
      echo "health unreachable (last HTTP $code after ${timeout}s)" >&2
      echo unknown
      return 0
    fi
    sleep 5
  done
}

case "$1" in
  ref) resolve_ref "$2" ;;
  health) resolve_health "$2" ;;
  *)
    usage
    exit 2
    ;;
esac
