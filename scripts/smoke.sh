#!/usr/bin/env bash
# End-to-end smoke test of the EchoNotes key journey (#24):
#   health -> SPA -> create project -> upload audio -> transcript -> screenshot -> export ZIP -> delete
#
# Usage: scripts/smoke.sh <base-url>          e.g. scripts/smoke.sh http://localhost:8000
#
# Needs only bash, curl and Python 3 (python3 or python) for JSON parsing, generating a 1 s
# silent WAV and a tiny PNG, and validating the ZIP. Works on Linux (CI) and Git Bash on Windows.
#
# Privacy: prints only step names, HTTP status codes, IDs, sizes and timings. Never response
# bodies, transcript text or secrets.
#
# Environment (all optional):
#   SMOKE_HEALTH_TIMEOUT=90     seconds to keep retrying /api/health (cold starts on Render)
#   SMOKE_REQUEST_TIMEOUT=120   max seconds per request (the audio upload waits for the provider)
#   SMOKE_ALLOW_EMPTY_TEXT=1    accept an empty transcript text (real Groq on silent audio)
#   SMOKE_SKIP_SPA=1            skip the SPA checks (API-only server, e.g. uvicorn without STATIC_DIR)
#   SMOKE_KEEP=1                keep the smoke project (skip the cleanup delete) for debugging
#   SMOKE_EXPECT_COMMIT=<sha>   fail unless /api/health reports this full commit SHA (deploys)
#
# The smoke project is named `smoke-test-<UTC timestamp>-<pid>`. An EXIT trap deletes it even
# when a step fails or the run is interrupted, so dev/prod keep no smoke data.
set -euo pipefail

usage() {
  echo "usage: $0 <base-url>   (e.g. $0 http://localhost:8000)" >&2
}

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  usage
  exit 2
fi

BASE_URL="${1%/}"
HEALTH_TIMEOUT="${SMOKE_HEALTH_TIMEOUT:-90}"
REQUEST_TIMEOUT="${SMOKE_REQUEST_TIMEOUT:-120}"

# ---------------------------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------------------------
pass() { printf 'PASS  %-22s %s\n' "$1" "$2"; }
info() { printf 'INFO  %s\n' "$*"; }
fail() {
  printf 'FAIL  %-22s %s\n' "$1" "$2"
  exit 1
}

# Strip any `user:password@` from the URL before printing it.
safe_url() { printf '%s' "$1" | sed -E 's#//[^/@]*@#//***@#'; }

# ---------------------------------------------------------------------------------------------
# Tooling: curl + a Python 3 that really runs (on Windows `python3` may be a Store stub)
# ---------------------------------------------------------------------------------------------
command -v curl >/dev/null 2>&1 || { echo "FAIL  prerequisites          curl not found" >&2; exit 1; }

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
    "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done
[ -n "$PY" ] || { echo "FAIL  prerequisites          no working python3/python found" >&2; exit 1; }

# Paths handed to native Windows programs (python.exe, curl.exe) must be Windows paths.
native_path() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/echonotes-smoke.XXXXXX")"
WORK="$(native_path "$WORK_DIR")"
PROJECT_ID=""

cleanup() {
  local status=$?
  set +e
  if [ -n "$PROJECT_ID" ]; then
    if [ "${SMOKE_KEEP:-}" = "1" ]; then
      info "SMOKE_KEEP=1: keeping project $PROJECT_ID"
    else
      local code
      code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 30 \
        -X DELETE "$BASE_URL/api/projects/$PROJECT_ID" 2>/dev/null)"
      if [ "$code" = "204" ]; then
        info "cleanup: deleted project $PROJECT_ID (HTTP 204)"
      else
        info "cleanup: could not delete project $PROJECT_ID (HTTP ${code:-none})"
      fi
    fi
  fi
  rm -rf "$WORK_DIR"
  if [ "$status" -eq 0 ]; then echo "SMOKE PASSED"; else echo "SMOKE FAILED (exit $status)"; fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# request <out-file> <curl args...>  -> sets CODE and TIME (seconds). Body goes to the file only.
CODE=""
TIME=""
request() {
  local out="$1"
  shift
  local result
  result="$(curl -sS -o "$out" -w '%{http_code} %{time_total}' --max-time "$REQUEST_TIMEOUT" \
    "$@" 2>/dev/null)" || result="000 0"
  CODE="${result%% *}"
  TIME="${result##* }"
}

# json_get <file> <key>  -> prints the top-level value (empty string for null/missing).
json_get() {
  "$PY" - "$1" "$2" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    value = json.load(fh).get(sys.argv[2])
print("" if value is None else value)
PY
}

info "base URL: $(safe_url "$BASE_URL")  python: $PY"

# ---------------------------------------------------------------------------------------------
# 1. Health (retries until the timeout; Render free instances cold-start)
# ---------------------------------------------------------------------------------------------
deadline=$(($(date +%s) + HEALTH_TIMEOUT))
attempt=0
while :; do
  attempt=$((attempt + 1))
  request "$WORK/health.json" "$BASE_URL/api/health"
  if [ "$CODE" = "200" ] && [ "$(json_get "$WORK/health.json" database 2>/dev/null)" = "ok" ]; then
    break
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    fail "health" "HTTP $CODE after $attempt attempts / ${HEALTH_TIMEOUT}s (want 200 + database ok)"
  fi
  sleep 3
done
version="$(json_get "$WORK/health.json" version)"
commit="$(json_get "$WORK/health.json" commit)"
environment="$(json_get "$WORK/health.json" environment)"
[ -n "$commit" ] || fail "health" "HTTP 200 but commit is missing or empty"
[ -n "$environment" ] || fail "health" "HTTP 200 but environment is missing or empty"
if [ -n "${SMOKE_EXPECT_COMMIT:-}" ] && [ "$commit" != "$SMOKE_EXPECT_COMMIT" ]; then
  fail "health" "commit $commit != expected $SMOKE_EXPECT_COMMIT (SMOKE_EXPECT_COMMIT)"
fi
pass "health" "HTTP 200 database=ok version=$version commit=${commit:0:7} environment=$environment attempts=$attempt ${TIME}s"

# ---------------------------------------------------------------------------------------------
# 2. SPA is served at / and for client routes; unknown /api paths stay JSON 404
# ---------------------------------------------------------------------------------------------
if [ "${SMOKE_SKIP_SPA:-}" = "1" ]; then
  info "SMOKE_SKIP_SPA=1: skipping SPA checks"
else
  for path in / /projects/smoke-route; do
    request "$WORK/spa.html" "$BASE_URL$path"
    if [ "$CODE" != "200" ] || ! grep -q '<div id="root">' "$WORK/spa.html"; then
      fail "spa $path" "HTTP $CODE (want 200 + index.html)"
    fi
    pass "spa $path" "HTTP 200 ${TIME}s"
  done
  request "$WORK/notfound.json" "$BASE_URL/api/smoke-does-not-exist"
  [ "$CODE" = "404" ] || fail "api unknown path" "HTTP $CODE (want 404)"
  pass "api unknown path" "HTTP 404 ${TIME}s"
fi

# ---------------------------------------------------------------------------------------------
# 3. Create a project with a unique name that is clearly a smoke project (safe on prod: the
#    EXIT trap deletes it even when a later step fails; only SMOKE_KEEP=1 skips that)
# ---------------------------------------------------------------------------------------------
project_name="smoke-test-$(date -u +%Y%m%dT%H%M%SZ)-$$"
request "$WORK/project.json" -X POST -H 'Content-Type: application/json' \
  -d "{\"name\":\"$project_name\"}" "$BASE_URL/api/projects"
[ "$CODE" = "201" ] || fail "create project" "HTTP $CODE (want 201)"
PROJECT_ID="$(json_get "$WORK/project.json" id)"
PROJECT_SLUG="$(json_get "$WORK/project.json" slug)"
[ -n "$PROJECT_ID" ] && [ -n "$PROJECT_SLUG" ] || fail "create project" "HTTP 201 but no id/slug"
pass "create project" "HTTP 201 id=$PROJECT_ID slug=$PROJECT_SLUG ${TIME}s"

# ---------------------------------------------------------------------------------------------
# 4. Generate a 1 s silent WAV and a tiny PNG (no binary fixtures in the repo)
# ---------------------------------------------------------------------------------------------
"$PY" - "$WORK/smoke.wav" "$WORK/smoke.png" <<'PY'
import struct, sys, wave, zlib

with wave.open(sys.argv[1], "wb") as wav:  # 1 s, mono, 16 kHz, 16-bit silence
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(16000)
    wav.writeframes(b"\x00\x00" * 16000)

def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

width = height = 4  # 4x4 RGB, one filter byte per row
raw = b"".join(b"\x00" + b"\x1f\x6f\xbf" * width for _ in range(height))
png = (
    b"\x89PNG\r\n\x1a\n"
    + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    + chunk(b"IDAT", zlib.compress(raw))
    + chunk(b"IEND", b"")
)
with open(sys.argv[2], "wb") as fh:
    fh.write(png)
PY

# ---------------------------------------------------------------------------------------------
# 5. Upload the audio -> transcript (synchronous)
# ---------------------------------------------------------------------------------------------
request "$WORK/upload.json" -X POST \
  -F "file=@$WORK/smoke.wav;type=audio/wav;filename=smoke.wav" -F "language=en" \
  "$BASE_URL/api/projects/$PROJECT_ID/transcriptions"
[ "$CODE" = "201" ] || fail "upload audio" "HTTP $CODE (want 201)"
TRANSCRIPT_ID="$(json_get "$WORK/upload.json" id)"
[ -n "$TRANSCRIPT_ID" ] || fail "upload audio" "HTTP 201 but no transcript id"
provider="$(json_get "$WORK/upload.json" provider)"
duration="$(json_get "$WORK/upload.json" duration_seconds)"
pass "upload audio" "HTTP 201 id=$TRANSCRIPT_ID provider=$provider duration=${duration:-?}s ${TIME}s"

# ---------------------------------------------------------------------------------------------
# 6. Read the transcript back (only its length is printed, never the text)
# ---------------------------------------------------------------------------------------------
request "$WORK/transcript.json" "$BASE_URL/api/transcriptions/$TRANSCRIPT_ID"
[ "$CODE" = "200" ] || fail "get transcript" "HTTP $CODE (want 200)"
text_chars="$("$PY" - "$WORK/transcript.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    print(len(json.load(fh).get("text") or ""))
PY
)"
if [ "$text_chars" -eq 0 ] && [ "${SMOKE_ALLOW_EMPTY_TEXT:-}" != "1" ]; then
  fail "get transcript" "HTTP 200 but text is empty (set SMOKE_ALLOW_EMPTY_TEXT=1 for real providers)"
fi
pass "get transcript" "HTTP 200 text_chars=$text_chars ${TIME}s"

# ---------------------------------------------------------------------------------------------
# 7. Upload a PNG screenshot linked to the transcript
# ---------------------------------------------------------------------------------------------
request "$WORK/screenshot.json" -X POST \
  -F "file=@$WORK/smoke.png;type=image/png;filename=smoke.png" \
  -F "transcript_id=$TRANSCRIPT_ID" \
  "$BASE_URL/api/projects/$PROJECT_ID/screenshots"
[ "$CODE" = "201" ] || fail "upload screenshot" "HTTP $CODE (want 201)"
SCREENSHOT_ID="$(json_get "$WORK/screenshot.json" id)"
linked="$(json_get "$WORK/screenshot.json" transcript_id)"
[ "$linked" = "$TRANSCRIPT_ID" ] || fail "upload screenshot" "HTTP 201 but not linked to the transcript"
size_bytes="$(json_get "$WORK/screenshot.json" size_bytes)"
pass "upload screenshot" "HTTP 201 id=$SCREENSHOT_ID size_bytes=$size_bytes linked=yes ${TIME}s"

# ---------------------------------------------------------------------------------------------
# 8. Export the project as a ZIP and validate its tree
# ---------------------------------------------------------------------------------------------
request "$WORK/export.zip" -D "$WORK/export.headers" "$BASE_URL/api/projects/$PROJECT_ID/export"
[ "$CODE" = "200" ] || fail "export zip" "HTTP $CODE (want 200)"
grep -qi '^content-type: *application/zip' "$WORK/export.headers" ||
  fail "export zip" "HTTP 200 but Content-Type is not application/zip"
zip_report="$("$PY" - "$WORK/export.zip" "$PROJECT_SLUG" <<'PY'
import fnmatch, sys, zipfile

path, slug = sys.argv[1], sys.argv[2]
try:
    archive = zipfile.ZipFile(path)
except zipfile.BadZipFile:
    print("not a valid ZIP")
    sys.exit(1)
with archive:
    bad = archive.testzip()
    if bad is not None:
        print("corrupt member in ZIP")
        sys.exit(1)
    names = archive.namelist()
required = {
    "README.md": f"{slug}/README.md",
    "transcripts/*.md": f"{slug}/transcripts/*.md",
    "transcripts/*.txt": f"{slug}/transcripts/*.txt",
    "screenshots/01-*.png": f"{slug}/screenshots/01-*.png",
}
missing = [label for label, pattern in required.items() if not fnmatch.filter(names, pattern)]
if missing:
    print("missing " + ", ".join(missing))
    sys.exit(1)
print(f"entries={len(names)}")
PY
)" || fail "export zip" "HTTP 200 but $zip_report"
zip_bytes="$(wc -c <"$WORK/export.zip" | tr -d ' ')"
pass "export zip" "HTTP 200 application/zip bytes=$zip_bytes $zip_report tree=ok ${TIME}s"

# ---------------------------------------------------------------------------------------------
# 9. Delete the project (the EXIT trap also does this when an earlier step failed)
# ---------------------------------------------------------------------------------------------
if [ "${SMOKE_KEEP:-}" = "1" ]; then
  info "SMOKE_KEEP=1: skipping delete"
else
  request "$WORK/delete.out" -X DELETE "$BASE_URL/api/projects/$PROJECT_ID"
  [ "$CODE" = "204" ] || fail "delete project" "HTTP $CODE (want 204)"
  PROJECT_ID=""
  pass "delete project" "HTTP 204 ${TIME}s"
fi
