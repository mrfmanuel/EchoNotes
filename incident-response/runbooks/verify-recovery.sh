#!/usr/bin/env bash
# Verify that the journey recovered after a fix was deployed to the local incident stack.
#
#   incident-response/runbooks/verify-recovery.sh http://localhost:8001
#
# Checks (all must pass, exit 0): health reports EXPECT_COMMIT, fresh traffic (same mix that
# caused the incident) has a 5xx ratio below VERIFY_THRESHOLD, Prometheus' counter delta for that
# traffic is below the threshold, and scripts/smoke.sh passes. The alert returning to Normal is
# reported but not required (Grafana needs a few evaluation cycles for the 2 m window).
#
# Environment: EXPECT_COMMIT, VERIFY_REQUESTS (20), VERIFY_THRESHOLD (0.2), VERIFY_ALERT_WAIT
# (seconds, default 240; 0 skips), GRAFANA_URL / GRAFANA_PORT / GRAFANA_USER / GRAFANA_PASSWORD.
# Prints Markdown (saved by the responder as verification.md). No bodies, text or secrets.
set -uo pipefail

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  echo "usage: $0 <app-base-url>" >&2
  exit 2
fi
APP_URL="${1%/}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
    "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done
[ -n "$PY" ] || { echo "no python3/python found" >&2; exit 1; }

echo "# Recovery verification"
echo
echo "- App: \`$APP_URL\`  expected commit: \`${EXPECT_COMMIT:-any}\`"
echo "- Started (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo

"$PY" "$here/verify_recovery.py" --app-url "$APP_URL" \
  --expect-commit "${EXPECT_COMMIT:-}" \
  --requests "${VERIFY_REQUESTS:-20}" \
  --threshold "${VERIFY_THRESHOLD:-0.2}" \
  --alert-wait "${VERIFY_ALERT_WAIT:-240}"
checks=$?

echo
echo "## Smoke test (scripts/smoke.sh)"
echo
echo '```text'
SMOKE_EXPECT_COMMIT="${EXPECT_COMMIT:-}" bash "$repo/scripts/smoke.sh" "$APP_URL" 2>&1
smoke=$?
echo '```'
echo

if [ "$checks" -eq 0 ] && [ "$smoke" -eq 0 ]; then
  echo "**Result: RECOVERED** (checks exit $checks, smoke exit $smoke)"
  exit 0
fi
echo "**Result: NOT RECOVERED** (checks exit $checks, smoke exit $smoke)"
exit 1
