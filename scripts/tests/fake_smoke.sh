#!/usr/bin/env bash
# Stub of scripts/smoke.sh for scripts/tests/test_deploy.sh. Checks that deploy.sh passes the
# expected environment, then exits with FAKE_SMOKE_EXIT (default 0).
set -euo pipefail
[ "$#" -eq 1 ] || { echo "fake smoke: want 1 arg, got $#" >&2; exit 97; }
[ "${SMOKE_ALLOW_EMPTY_TEXT:-}" = "1" ] || { echo "fake smoke: SMOKE_ALLOW_EMPTY_TEXT!=1" >&2; exit 98; }
[ -n "${SMOKE_EXPECT_COMMIT:-}" ] || { echo "fake smoke: SMOKE_EXPECT_COMMIT unset" >&2; exit 99; }
echo "fake smoke: url=$1 expect_commit=$SMOKE_EXPECT_COMMIT"
exit "${FAKE_SMOKE_EXIT:-0}"
