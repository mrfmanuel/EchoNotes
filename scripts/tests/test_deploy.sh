#!/usr/bin/env bash
# Tests for scripts/deploy.sh and scripts/resolve-commit.sh against a local mock of the Render
# deploy hook + /api/health (scripts/tests/deploy_mock.py). Never calls the real Render hooks.
#
# Usage: bash scripts/tests/test_deploy.sh        (Linux or Git Bash; needs curl + Python 3)
# Takes about 30 s. Exit 0 = all cases passed.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$(cd "$HERE/.." && pwd)"
DEPLOY="$SCRIPTS/deploy.sh"
RESOLVE="$SCRIPTS/resolve-commit.sh"

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
    "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done
[ -n "$PY" ] || { echo "no working python3/python found" >&2; exit 1; }
native_path() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

TMP="$(mktemp -d "${TMPDIR:-/tmp}/echonotes-deploy-test.XXXXXX")"
PORT_FILE="$TMP/port"
MOCK_PID=""
BASE=""

cleanup() {
  set +e
  if [ -n "$BASE" ]; then curl -s -X POST --max-time 5 "$BASE/_shutdown" >/dev/null 2>&1; fi
  if [ -n "$MOCK_PID" ]; then
    kill "$MOCK_PID" 2>/dev/null
    wait "$MOCK_PID" 2>/dev/null
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

# Start the mock on a free port chosen by the OS (port 0); it writes the port to a file.
"$PY" "$(native_path "$HERE/deploy_mock.py")" "$(native_path "$PORT_FILE")" &
MOCK_PID=$!
for _ in $(seq 1 50); do
  [ -s "$PORT_FILE" ] && break
  sleep 0.2
done
[ -s "$PORT_FILE" ] || { echo "mock server did not start" >&2; exit 1; }
BASE="http://127.0.0.1:$(cat "$PORT_FILE")"

SECRET_KEY="s3cr3t-hook-key-DO-NOT-PRINT"
HOOK="$BASE/hook?key=$SECRET_KEY"
SHA="0123456789abcdef0123456789abcdef01234567"
OLD="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

PASSED=0
FAILED=0
ALL_OUTPUT="$TMP/all-output.txt"
: >"$ALL_OUTPUT"

ok() { PASSED=$((PASSED + 1)); printf 'ok    %s\n' "$1"; }
not_ok() { FAILED=$((FAILED + 1)); printf 'FAIL  %s: %s\n' "$1" "$2"; }

mock_reset() { curl -sf -X POST --max-time 5 "$BASE/_reset?$1" >/dev/null; }
mock_state() {
  curl -sf --max-time 5 "$BASE/_state" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"
}

# run_deploy <name> <env-name> <sha> [VAR=value ...] -> sets RC, OUT (file), SUMMARY (file)
RC=0
OUT=""
SUMMARY=""
run_deploy() {
  local name="$1" env_name="$2" sha="$3"
  shift 3
  OUT="$TMP/$name.out"
  SUMMARY="$TMP/$name.summary.md"
  : >"$SUMMARY"
  RC=0
  env DEPLOY_HOOK_URL="$HOOK" DEPLOY_POLL_INTERVAL=1 DEPLOY_TIMEOUT=10 DEPLOY_HOOK_WAIT=10 \
    DEPLOY_HOOK_BACKOFF=1 SMOKE_SCRIPT="$HERE/fake_smoke.sh" GITHUB_STEP_SUMMARY="$SUMMARY" \
    "$@" bash "$DEPLOY" "$env_name" "$BASE" "$sha" >"$OUT" 2>&1 || RC=$?
  cat "$OUT" "$SUMMARY" >>"$ALL_OUTPUT"
}

expect_rc() {
  if [ "$RC" -eq "$2" ]; then return 0; fi
  not_ok "$1" "exit $RC, want $2"
  sed 's/^/        | /' "$OUT"
  return 1
}
expect_in() {
  if grep -q -- "$3" "$2"; then return 0; fi
  not_ok "$1" "'$3' not found in $(basename "$2")"
  sed 's/^/        | /' "$2"
  return 1
}
expect_eq() {
  if [ "$2" = "$3" ]; then return 0; fi
  not_ok "$1" "got '$2', want '$3'"
  return 1
}

# ---------------------------------------------------------------------------------------------
# deploy.sh
# ---------------------------------------------------------------------------------------------
t="success: hook 200, health 503 then old commit then new commit, smoke passes"
mock_reset "key=$SECRET_KEY&initial=$OLD&fail_first=1&flip_after=3&env=dev"
run_deploy success dev "$SHA"
expect_rc "$t" 0 &&
  expect_eq "$t (ref sent to hook)" "$(mock_state last_ref)" "$SHA" &&
  expect_in "$t" "$OUT" "fake smoke: url=$BASE expect_commit=$SHA" &&
  expect_in "$t" "$SUMMARY" "| Target commit | \`$SHA\` |" &&
  expect_in "$t" "$SUMMARY" "| Running before | \`$OLD\` |" &&
  expect_in "$t" "$SUMMARY" "| Render deploy id | dep-mock1 |" &&
  expect_in "$t" "$SUMMARY" "| Result | success |" &&
  ok "$t"

t="success with PREVIOUS_COMMIT and custom summary title"
mock_reset "key=$SECRET_KEY&initial=$OLD&flip_after=1&env=prod"
run_deploy previous prod "$SHA" PREVIOUS_COMMIT="$OLD" DEPLOY_SUMMARY_TITLE="Promote to prod"
expect_rc "$t" 0 &&
  expect_in "$t" "$SUMMARY" "### Promote to prod" &&
  expect_in "$t" "$SUMMARY" "| Previous commit (recorded by workflow) | \`$OLD\` |" &&
  ok "$t"

t="pre-#47 service (no commit/environment in health before deploy) records 'unknown'"
mock_reset "key=$SECRET_KEY&initial=&env=&flip_after=1"
run_deploy legacy dev "$SHA"
expect_rc "$t" 0 && expect_in "$t" "$SUMMARY" "| Running before | \`unknown\` |" && ok "$t"

t="202 (deploy in progress) is retried with backoff, then 200"
mock_reset "key=$SECRET_KEY&busy=2&flip_after=0"
run_deploy busy dev "$SHA"
expect_rc "$t" 0 && expect_eq "$t (hook calls)" "$(mock_state hook_calls)" "3" &&
  expect_in "$t" "$OUT" "HTTP 202, another deploy is in progress" && ok "$t"

t="202 for longer than DEPLOY_HOOK_WAIT fails"
mock_reset "key=$SECRET_KEY&busy=1000"
run_deploy busy-forever dev "$SHA" DEPLOY_HOOK_WAIT=2
expect_rc "$t" 1 && expect_in "$t" "$SUMMARY" "FAILED\*\* at step: trigger hook" && ok "$t"

t="404 (unknown SHA) fails without polling health"
mock_reset "key=$SECRET_KEY&hook_status=404"
run_deploy notfound dev "$SHA"
expect_rc "$t" 1 && expect_in "$t" "$OUT" "HTTP 404" &&
  expect_eq "$t (health calls: only the 'before' read)" "$(mock_state health_calls)" "1" &&
  expect_in "$t" "$SUMMARY" "at step: trigger hook" && ok "$t"

t="wrong hook key (404) fails"
mock_reset "key=another-key"
run_deploy badkey dev "$SHA"
expect_rc "$t" 1 && expect_in "$t" "$OUT" "HTTP 404" && ok "$t"

t="other hook status (500) fails"
mock_reset "key=$SECRET_KEY&hook_status=500"
run_deploy hook500 dev "$SHA"
expect_rc "$t" 1 && expect_in "$t" "$OUT" "HTTP 500 (expected 200)" && ok "$t"

t="unreachable hook (connection refused) fails with status 000 only"
run_deploy unreachable dev "$SHA" DEPLOY_HOOK_URL="http://127.0.0.1:1/hook?key=$SECRET_KEY"
expect_rc "$t" 1 && expect_in "$t" "$OUT" "HTTP 000" && ok "$t"

t="health never reports the commit -> timeout failure"
mock_reset "key=$SECRET_KEY&initial=$OLD&flip_after=-1"
run_deploy timeout dev "$SHA" DEPLOY_TIMEOUT=3
expect_rc "$t" 1 && expect_in "$t" "$SUMMARY" "at step: verify commit" &&
  expect_in "$t" "$OUT" "did not report $SHA within 3s" && ok "$t"

t="smoke failure fails the deploy"
mock_reset "key=$SECRET_KEY&flip_after=0"
run_deploy smokefail dev "$SHA" FAKE_SMOKE_EXIT=1
expect_rc "$t" 1 && expect_in "$t" "$SUMMARY" "at step: smoke test" && ok "$t"

t="environment mismatch (hook/URL of another env) fails"
mock_reset "key=$SECRET_KEY&flip_after=0&env=prod"
run_deploy envmismatch dev "$SHA"
expect_rc "$t" 1 && expect_in "$t" "$SUMMARY" "at step: verify environment" && ok "$t"

t="invalid SHA (short) is a usage error and never calls the hook"
mock_reset "key=$SECRET_KEY"
run_deploy shortsha dev "0123456"
expect_rc "$t" 2 && expect_eq "$t (hook calls)" "$(mock_state hook_calls)" "0" && ok "$t"

t="missing DEPLOY_HOOK_URL is a usage error"
run_deploy nohook dev "$SHA" DEPLOY_HOOK_URL=
expect_rc "$t" 2 && expect_in "$t" "$OUT" "DEPLOY_HOOK_URL is not set" && ok "$t"

t="GitHub Actions: hook URL and key are masked with ::add-mask::"
mock_reset "key=$SECRET_KEY&flip_after=0"
run_deploy masked dev "$SHA" GITHUB_ACTIONS=true
expect_rc "$t" 0 && expect_in "$t" "$OUT" "::add-mask::" && ok "$t"

t="the hook key never appears in output or summaries (except ::add-mask:: commands)"
if grep -v '^::add-mask::' "$ALL_OUTPUT" | grep -q -- "$SECRET_KEY"; then
  not_ok "$t" "secret found in output"
  grep -v '^::add-mask::' "$ALL_OUTPUT" | grep -n -- "$SECRET_KEY" | sed 's/^/        | /'
else
  ok "$t"
fi

# ---------------------------------------------------------------------------------------------
# resolve-commit.sh
# ---------------------------------------------------------------------------------------------
t="resolve health: returns the running commit"
mock_reset "key=$SECRET_KEY&initial=$OLD"
got="$(bash "$RESOLVE" health "$BASE" 2>/dev/null)" || true
expect_eq "$t" "$got" "$OLD" && ok "$t"

t="resolve health: missing commit field -> unknown"
mock_reset "key=$SECRET_KEY&initial="
got="$(bash "$RESOLVE" health "$BASE" 2>/dev/null)" || true
expect_eq "$t" "$got" "unknown" && ok "$t"

t="resolve health: unreachable -> unknown (exit 0)"
got="$(RESOLVE_HEALTH_TIMEOUT=0 bash "$RESOLVE" health "http://127.0.0.1:1" 2>/dev/null)" || true
expect_eq "$t" "$got" "unknown" && ok "$t"

if git -C "$SCRIPTS" rev-parse --verify --quiet origin/main >/dev/null; then
  main_sha="$(git -C "$SCRIPTS" rev-parse origin/main)"
  t="resolve ref: short SHA on origin/main -> full SHA"
  got="$(cd "$SCRIPTS" && bash "$RESOLVE" ref "${main_sha:0:8}" 2>/dev/null)" || true
  expect_eq "$t" "$got" "$main_sha" && ok "$t"

  t="resolve ref: uppercase full SHA accepted"
  got="$(cd "$SCRIPTS" && bash "$RESOLVE" ref "$(printf '%s' "$main_sha" | tr 'a-f' 'A-F')" 2>/dev/null)" || true
  expect_eq "$t" "$got" "$main_sha" && ok "$t"

  t="resolve ref: commit not on main is rejected"
  if (cd "$SCRIPTS" && RESOLVE_MAIN_REF="origin/main~1" bash "$RESOLVE" ref "$main_sha" >/dev/null 2>&1); then
    not_ok "$t" "accepted"
  else
    ok "$t"
  fi
else
  echo "skip  resolve ref tests (no origin/main in this checkout)"
fi

for bad in main HEAD "--help" "xyz1234" "0000000000000000000000000000000000000000"; do
  t="resolve ref: rejects '$bad'"
  if (cd "$SCRIPTS" && bash "$RESOLVE" ref "$bad" >/dev/null 2>&1); then
    not_ok "$t" "accepted"
  else
    ok "$t"
  fi
done

echo ""
echo "deploy tests: $PASSED passed, $FAILED failed"
[ "$FAILED" -eq 0 ]
