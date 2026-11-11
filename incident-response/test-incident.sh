#!/usr/bin/env bash
# One-command on-call demo (US-21 AC4):
#
#   incident-response/test-incident.sh             # run the whole loop
#   incident-response/test-incident.sh --cleanup   # remove the incident stack, worktrees, images
#   incident-response/test-incident.sh --cleanup --delete-remote   # ...and the pushed branches
#
#  1. git worktree on a NEW branch chaos/INC-<id> from BASE_REF (default origin/main), apply
#     incident-response/chaos/$CHAOS_PATCH and commit it there (never on main)
#  2. push chaos/INC-<id> (the base of the responder's PR, so its diff shows only the fix)
#  3. start app + Postgres + grafana/otel-lgtm from that worktree (docker-compose.yml, profile
#     `observability`) as compose project `echonotes-incident` with its own image tag
#     (APP_IMAGE), APP_PORT 8001 and GRAFANA_PORT 3001; the `echonotes` stack is never touched
#  4. start the responder on ONCALL_PORT (9095) for exactly one incident
#  5. fake-provider traffic until the alert fires and the responder opens the incident
#  6. wait for the responder, print the incident folder and the PR URL
#
# The stack keeps running afterwards (for screenshots); `--cleanup` removes it. Run from Git Bash
# on Windows or any POSIX shell. Needs: git, gh (logged in), docker compose, uv, claude.
#
# Environment (optional): BASE_REF, CHAOS_PATCH, INCIDENT_PROJECT (echonotes-incident), APP_PORT,
# GRAFANA_PORT, ONCALL_PORT, ALERT_TIMEOUT (s, 900), RESPONDER_TIMEOUT (s, 3600),
# INCIDENT_PUSH=0 (no push, no PR), ONCALL_AGENT_CMD (+ ONCALL_STUB_SCENARIO) to replace claude
# with a stub, OBS_OTLP_ENDPOINT (default http://lgtm:4318).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(git -C "$here" rev-parse --show-toplevel)"
work="$here/.work"
project="${INCIDENT_PROJECT:-echonotes-incident}"

export APP_PORT="${APP_PORT:-8001}"
export GRAFANA_PORT="${GRAFANA_PORT:-3001}"
export ONCALL_PORT="${ONCALL_PORT:-9095}"
export COMPOSE_PROJECT="$project"
export OBS_OTLP_ENDPOINT="${OBS_OTLP_ENDPOINT:-http://lgtm:4318}"
export ONCALL_WEBHOOK_URL="http://host.docker.internal:$ONCALL_PORT/alert"
BASE_REF="${BASE_REF:-origin/main}"
CHAOS_PATCH="${CHAOS_PATCH:-realtime-factor-zero-division.patch}"
ALERT_TIMEOUT="${ALERT_TIMEOUT:-900}"
RESPONDER_TIMEOUT="${RESPONDER_TIMEOUT:-3600}"

say() { printf '\n==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
    "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    PY="$candidate"; break
  fi
done
[ -n "$PY" ] || die "no python3/python found"

# The responder's work dir (agent worktrees, dedupe state) is OUTSIDE the repo tree.
if [ -z "${ONCALL_WORK_DIR:-}" ]; then
  ONCALL_WORK_DIR="$("$PY" -c 'import os, tempfile; print(os.path.join(tempfile.gettempdir(), "echonotes-oncall"))')"
fi
export ONCALL_WORK_DIR
oncall_work="$ONCALL_WORK_DIR"
if command -v cygpath >/dev/null 2>&1; then oncall_work="$(cygpath -u "$ONCALL_WORK_DIR")"; fi

# Fixed, safe values for every compose call (docker-compose.yml interface of #30): own project,
# ports, fake provider, no Groq key, OTLP to the lgtm service, alert webhook to the responder.
compose_env() {
  env COMPOSE_PROJECT_NAME="$project" TRANSCRIBER_PROVIDER=fake GROQ_API_KEY= \
    APP_PORT="$APP_PORT" GRAFANA_PORT="$GRAFANA_PORT" OBS_OTLP_ENDPOINT="$OBS_OTLP_ENDPOINT" \
    ONCALL_WEBHOOK_URL="$ONCALL_WEBHOOK_URL" "$@"
}

cleanup() {
  local delete_remote="$1"
  say "cleanup: compose project $project"
  if [ -f "$repo/docker-compose.yml" ]; then
    (cd "$repo" && compose_env docker compose -p "$project" --profile observability \
      down -v --remove-orphans) || true
  fi
  say "cleanup: worktrees and local branches"
  for dir in "$work"/chaos-INC-* "$oncall_work"/oncall-INC-* "$oncall_work"/repro-INC-* \
    "$oncall_work"/verify-INC-*; do
    [ -e "$dir" ] || continue
    git -C "$repo" worktree remove --force "$dir" 2>/dev/null || rm -rf "$dir"
  done
  git -C "$repo" worktree prune
  for branch in $(git -C "$repo" for-each-ref --format='%(refname:short)' 'refs/heads/chaos/INC-*' 'refs/heads/oncall/INC-*'); do
    if [ "$delete_remote" = "1" ]; then
      git -C "$repo" push origin --delete "$branch" 2>/dev/null || true
    fi
    git -C "$repo" branch -D "$branch" >/dev/null 2>&1 || true
  done
  say "cleanup: images echonotes-incident:*"
  for image in $(docker image ls --format '{{.Repository}}:{{.Tag}}' 'echonotes-incident' 2>/dev/null); do
    docker image rm "$image" >/dev/null 2>&1 || true
  done
  rm -f "$oncall_work/state.json" "$work"/responder-*.log
  rm -rf "$oncall_work/sandbox"
  echo "cleanup done (incident folders in incident-response/incidents/ are kept)"
}

if [ "${1:-}" = "--cleanup" ]; then
  cleanup "$([ "${2:-}" = "--delete-remote" ] && echo 1 || echo 0)"
  exit 0
fi
[ "$#" -eq 0 ] || die "usage: $0 [--cleanup [--delete-remote]]"

# --- preflight -------------------------------------------------------------------------------------
say "preflight"
for tool in git docker uv curl; do command -v "$tool" >/dev/null || die "$tool not found"; done
if [ -z "${ONCALL_AGENT_CMD:-}" ]; then command -v claude >/dev/null || die "claude not found"; fi
if [ "${INCIDENT_PUSH:-1}" = "1" ]; then gh auth status >/dev/null 2>&1 || die "gh is not logged in"; fi
port_busy() { "$PY" -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1', int(sys.argv[1])))==0 else 1)" "$1"; }
for port in "$APP_PORT" "$GRAFANA_PORT" "$ONCALL_PORT"; do
  if port_busy "$port"; then
    die "port $port is in use (stack already running? try --cleanup). Nothing was changed."
  fi
done
git -C "$repo" fetch --quiet origin
base_sha="$(git -C "$repo" rev-parse --verify "$BASE_REF^{commit}")" || die "unknown BASE_REF $BASE_REF"
patch="$here/chaos/$CHAOS_PATCH"
[ -f "$patch" ] || die "chaos patch not found: $patch"

ID="INC-$(date -u +%Y%m%d-%H%M%S)"
chaos_branch="chaos/$ID"
chaos_wt="$work/chaos-$ID"
mkdir -p "$work" "$here/incidents"
rm -f "$oncall_work/state.json"   # a fresh demo must not be de-duplicated against an old run
echo "incident id: $ID   base: $BASE_REF ($(git -C "$repo" rev-parse --short "$base_sha"))"

# --- 1. chaos worktree + commit -------------------------------------------------------------------
say "1/6 chaos worktree $chaos_branch with $CHAOS_PATCH"
git -C "$repo" worktree add --quiet -b "$chaos_branch" "$chaos_wt" "$base_sha"
git -C "$chaos_wt" apply --3way "$patch" || die "chaos patch does not apply to $BASE_REF (see chaos/README.md)"
git -C "$chaos_wt" add -A
git -C "$chaos_wt" commit --quiet -m "perf(transcription): log the real-time factor of each transcription" \
  -m "[chaos] Injected by incident-response/test-incident.sh for $ID from incident-response/chaos/$CHAOS_PATCH. Throwaway incident branch: never merge into main."
chaos_sha="$(git -C "$chaos_wt" rev-parse HEAD)"
echo "chaos commit $chaos_sha"

# --- 2. push the chaos base branch ----------------------------------------------------------------
if [ "${INCIDENT_PUSH:-1}" = "1" ]; then
  say "2/6 push $chaos_branch (PR base)"
  git -C "$chaos_wt" push --quiet -u origin "$chaos_branch"
else
  say "2/6 INCIDENT_PUSH=0: not pushing (the responder will not push or open a PR)"
  export ONCALL_PUBLISH=0
fi

# --- 3. stack ---------------------------------------------------------------------------------------
say "3/6 start $project (app :$APP_PORT, Grafana :$GRAFANA_PORT) from the chaos worktree"
grep -q 'profiles: \[observability\]' "$chaos_wt/docker-compose.yml" ||
  die "docker-compose.yml at $BASE_REF has no observability profile (needs #30)"
(cd "$chaos_wt" && compose_env GIT_SHA="$chaos_sha" \
  APP_IMAGE="echonotes-incident:$(echo "$ID" | tr 'A-Z' 'a-z')-chaos" \
  docker compose -p "$project" --profile observability up -d --build --wait)
curl -fsS "http://localhost:$APP_PORT/api/health" >/dev/null || die "app not healthy on :$APP_PORT"
echo "app:     http://localhost:$APP_PORT"
echo "grafana: http://localhost:$GRAFANA_PORT  (admin/admin, local only)"

# --- 4. responder -------------------------------------------------------------------------------------
say "4/6 responder on 127.0.0.1:$ONCALL_PORT"
log="$work/responder-$ID.log"
(cd "$repo" && ONCALL_INCIDENT_ID="$ID" ONCALL_PR_BASE="$chaos_branch" ONCALL_PORT="$ONCALL_PORT" \
  exec uv run --quiet incident-response/responder.py --exit-after-incidents 1 >"$log" 2>&1) &
responder_pid=$!
for _ in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:$ONCALL_PORT/healthz" >/dev/null 2>&1 && break
  kill -0 "$responder_pid" 2>/dev/null || { cat "$log"; die "responder exited early"; }
  sleep 1
done
curl -fsS "http://127.0.0.1:$ONCALL_PORT/healthz" >/dev/null || die "responder not reachable"
echo "responder log: $log"

# --- 5. traffic until the alert fires ----------------------------------------------------------------
say "5/6 fake-provider traffic until the alert fires (timeout ${ALERT_TIMEOUT}s)"
incident_dir="$here/incidents/$ID"
deadline=$(( $(date +%s) + ALERT_TIMEOUT ))
while [ ! -f "$incident_dir/incident.json" ]; do
  [ "$(date +%s)" -lt "$deadline" ] || die "alert did not fire within ${ALERT_TIMEOUT}s (check Grafana alerting)"
  kill -0 "$responder_pid" 2>/dev/null || { tail -20 "$log"; die "responder stopped"; }
  "$PY" "$here/traffic.py" --base-url "http://localhost:$APP_PORT" --requests 10 --interval 0.3 || true
done
echo "alert received: $incident_dir"

# --- 6. wait for the responder ---------------------------------------------------------------------
say "6/6 waiting for the responder (agent, policy, PR, rebuild, verification; timeout ${RESPONDER_TIMEOUT}s)"
deadline=$(( $(date +%s) + RESPONDER_TIMEOUT ))
last=""
while kill -0 "$responder_pid" 2>/dev/null; do
  status="$("$PY" -c "import json,sys; print(json.load(open(sys.argv[1], encoding='utf-8')).get('status',''))" "$incident_dir/incident.json" 2>/dev/null || true)"
  [ "$status" = "$last" ] || { echo "status: $status"; last="$status"; }
  if [ "$(date +%s)" -ge "$deadline" ]; then
    kill "$responder_pid" 2>/dev/null || true   # our own child, by PID
    die "responder did not finish within ${RESPONDER_TIMEOUT}s"
  fi
  sleep 5
done
wait "$responder_pid" || true

"$PY" - "$incident_dir/incident.json" <<'PY'
import json, sys
state = json.load(open(sys.argv[1], encoding="utf-8"))
print()
print(f"incident:  {state.get('incident_id')}  status={state.get('status')}")
print(f"folder:    incident-response/incidents/{state.get('incident_id')}/")
no_pr = "none (see escalation.md)" if state.get("status") == "escalated" else "none (publish off)"
print(f"PR:        {state.get('pr_url', no_pr)}")
print(f"fix:       {state.get('fix_commit', 'none')}")
PY
echo "grafana:   http://localhost:$GRAFANA_PORT  (stack left running for screenshots)"
echo "cleanup:   incident-response/test-incident.sh --cleanup"
