#!/usr/bin/env bash
# Thin wrapper so the module layout (`collect-evidence.sh`) works; the logic is in
# collect_evidence.py (stdlib only, read-only, allowlisted, bounded, scrubbed).
#   incident-response/collect-evidence.sh --incident-id INC-x --out /path/evidence.json
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --no-project --quiet python "$here/collect_evidence.py" "$@"
