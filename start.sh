#!/usr/bin/env bash
# PENUMBRA.AI - run the website and the API on this computer (macOS / Linux).
#
#   bash start.sh                  website + API
#   bash start.sh --website-only   website only; the app runs in demo mode
#
# The first run installs everything (a few minutes). Ctrl+C stops both servers.
# Windows: double-click start.bat instead.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND="$ROOT/frontend"
BACKEND="$ROOT/backend"
SITE_URL="http://localhost:3000"
API_URL="http://localhost:8000"
WEBSITE_ONLY=0
[[ "${1:-}" == "--website-only" ]] && WEBSITE_ONLY=1

cyan() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
green() { printf '  \033[32m%s\033[0m\n' "$1"; }
yellow() { printf '  \033[33m%s\033[0m\n' "$1"; }
fail() { printf '\n  \033[31m%s\033[0m\n\n' "$1"; exit 1; }

up() { curl -fsS -o /dev/null --max-time 2 "$1" 2>/dev/null; }
wait_for() {
  local url="$1" seconds="$2"
  for _ in $(seq 1 "$seconds"); do up "$url" && return 0; sleep 1; done
  return 1
}
sha() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

PIDS=()
cleanup() {
  [[ ${#PIDS[@]} -gt 0 ]] && kill "${PIDS[@]}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

printf '\n  \033[35mPENUMBRA.AI  -  local launcher\033[0m\n'

# -- 1. Node.js ------------------------------------------------------------------
cyan "Checking Node.js"
command -v node >/dev/null || fail "Node.js is not installed. Install the LTS version from https://nodejs.org and run bash start.sh again."
NODE_VERSION="$(node --version | sed 's/^v//')"
(( ${NODE_VERSION%%.*} >= 18 )) || fail "Node.js $NODE_VERSION is too old. Install Node 20 LTS from https://nodejs.org."
green "Node.js $NODE_VERSION"

# -- 2. Website dependencies -----------------------------------------------------
cyan "Preparing the website"
LOCK_HASH="$(sha "$FRONTEND/package-lock.json")"
if [[ "$(cat "$FRONTEND/node_modules/.penumbra-lock" 2>/dev/null || true)" != "$LOCK_HASH" ]]; then
  echo "  Installing website dependencies (about a minute the first time)..."
  (cd "$FRONTEND" && npm ci --no-audit --no-fund) || fail "Installing the website dependencies failed."
  echo "$LOCK_HASH" > "$FRONTEND/node_modules/.penumbra-lock"
fi
green "Website dependencies ready."

# -- 3. Backend ------------------------------------------------------------------
API_STATE="skipped"
find_python() {
  # TenSEAL 0.3.17 ships wheels for Python 3.11 to 3.14.
  for candidate in python3.13 python3.12 python3.11 python3.14 python3 python; do
    command -v "$candidate" >/dev/null || continue
    local version
    version="$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" || continue
    local minor="${version#3.}"
    if [[ "$version" == 3.* ]] && (( minor >= 11 && minor <= 14 )); then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

if (( WEBSITE_ONLY )); then
  cyan "Skipping the backend (website-only mode)"
elif up "$API_URL/health"; then
  cyan "Backend"
  green "An API is already answering on port 8000 - using it."
  API_STATE="running"
else
  cyan "Preparing the backend (Python API)"
  if ! PYTHON="$(find_python)"; then
    yellow "Python 3.11 - 3.14 was not found, so the API will not start."
    yellow "The website still works in demo mode. Install Python 3.12 and run bash start.sh again."
  else
    echo "  Using $("$PYTHON" --version)"
    VENV="$BACKEND/.venv"
    [[ -x "$VENV/bin/python" ]] || "$PYTHON" -m venv "$VENV"
    REQ_HASH="$(sha "$BACKEND/requirements.txt")"
    if [[ "$(cat "$VENV/.penumbra-requirements" 2>/dev/null || true)" != "$REQ_HASH" ]]; then
      echo "  Installing backend packages - TenSEAL, NumPy, SciPy, FastAPI (first run: a few minutes)..."
      "$VENV/bin/python" -m pip install --upgrade pip --quiet --disable-pip-version-check
      "$VENV/bin/python" -m pip install -r "$BACKEND/requirements.txt" --disable-pip-version-check \
        && echo "$REQ_HASH" > "$VENV/.penumbra-requirements"
    fi
    if [[ "$(cat "$VENV/.penumbra-requirements" 2>/dev/null || true)" == "$REQ_HASH" ]]; then
      if [[ ! -f "$BACKEND/.env" ]]; then
        SECRET="$("$VENV/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))')"
        sed "s|^JWT_SECRET=.*|JWT_SECRET=$SECRET|" "$BACKEND/.env.example" > "$BACKEND/.env"
        echo "  Created backend/.env with a fresh random JWT secret."
      fi
      (cd "$BACKEND" && exec "$VENV/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
      PIDS+=("$!")
      if wait_for "$API_URL/health" 90; then
        green "API is up at $API_URL  (docs: $API_URL/docs)"
        API_STATE="running"
      else
        yellow "The API did not answer within 90 seconds - see the log above."
      fi
    else
      yellow "Installing the backend packages failed; continuing without the API."
    fi
  fi
fi

# -- 4. Website ------------------------------------------------------------------
cyan "Starting the website"
if up "$SITE_URL"; then
  green "Something is already serving $SITE_URL."
else
  (cd "$FRONTEND" && exec npm run dev -- --strictPort) &
  PIDS+=("$!")
  wait_for "$SITE_URL" 90 || fail "The website did not start within 90 seconds - see the log above."
fi

if [[ -z "${NO_BROWSER:-}" ]]; then
  if command -v open >/dev/null; then open "$SITE_URL"; elif command -v xdg-open >/dev/null; then xdg-open "$SITE_URL" >/dev/null 2>&1 || true; fi
fi

printf '\n  ------------------------------------------------------------\n'
green "Website   $SITE_URL"
if [[ "$API_STATE" == "running" ]]; then green "API       $API_URL/docs   (status on the site: Online)"; else yellow "API       not running    (status on the site: Demo Mode)"; fi
printf '  Press Ctrl+C to stop.\n  ------------------------------------------------------------\n\n'

if [[ ${#PIDS[@]} -gt 0 ]]; then wait; fi
