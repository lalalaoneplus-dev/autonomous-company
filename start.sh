#!/usr/bin/env bash
# Start the local API and dashboard in the background.
# Restarts only processes recorded in .run/*.pid. A port held by anything else
# stops the launch.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="${ROOT}/.run"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
API_URL="http://127.0.0.1:${API_PORT}"
WEB_URL="http://127.0.0.1:${WEB_PORT}"

die() {
  echo "$*" >&2
  exit 1
}

export PNPM_HOME="${PNPM_HOME:-${HOME}/Library/pnpm}"
export PATH="${ROOT}/.node/bin:${HOME}/.local/bin:${PNPM_HOME}:${PNPM_HOME}/bin:${HOME}/.local/share/pnpm:${PATH}"

if [[ -x "${ROOT}/.node/bin/node" ]]; then
  export PATH="${ROOT}/.node/bin:${PATH}"
fi

command -v uv >/dev/null 2>&1 || die "uv is required. Re-run install.sh."
command -v pnpm >/dev/null 2>&1 || die "pnpm is required. Re-run install.sh."
[[ -f "${ROOT}/.env" ]] || die "Missing ${ROOT}/.env. Re-run install.sh."
[[ -x "${ROOT}/apps/api/.venv/bin/python" ]] || die "Python 3.12 virtualenv is missing. Re-run install.sh."

if [[ ! "$API_PORT" =~ ^[0-9]+$ ]]; then
  die "API_PORT must be a number."
fi
if [[ ! "$WEB_PORT" =~ ^[0-9]+$ ]]; then
  die "WEB_PORT must be a number."
fi

lsof_cmd() {
  if command -v lsof >/dev/null 2>&1; then
    command -v lsof
    return 0
  fi
  if [[ -x /usr/sbin/lsof ]]; then
    printf '%s\n' /usr/sbin/lsof
    return 0
  fi
  return 1
}

port_busy() {
  local port=$1
  local bin
  bin="$(lsof_cmd)" || return 1
  if "$bin" -nP -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

bash "${ROOT}/stop.sh"
sleep 0.3

if port_busy "$API_PORT"; then
  sleep 0.5
fi
if port_busy "$API_PORT"; then
  die "Port ${API_PORT} is in use. Choose another with API_PORT=<port>."
fi
if port_busy "$WEB_PORT"; then
  sleep 0.5
fi
if port_busy "$WEB_PORT"; then
  die "Port ${WEB_PORT} is in use. Choose another with WEB_PORT=<port>."
fi

mkdir -p "$RUN_DIR"

start_locked() {
  local pidfile=$1
  local logfile=$2
  local workdir=$3
  shift 3
  local lock="${pidfile}.lock"
  : >"$lock"
  nohup bash -c 'set -euo pipefail; cd "$1"; exec 9>"$2"; printf "%s\n" "$$" > "$3"; shift 3; exec "$@"' _ "$workdir" "$lock" "$pidfile" "$@" >"$logfile" 2>&1 &
}

start_locked "${RUN_DIR}/api.pid" "${ROOT}/api.log" "${ROOT}/apps/api" \
  "${ROOT}/apps/api/.venv/bin/python" -m uvicorn app.main:app --reload --port "$API_PORT"

start_locked "${RUN_DIR}/web.pid" "${ROOT}/web.log" "${ROOT}/apps/web" \
  env BROWSER=none "${ROOT}/apps/web/node_modules/.bin/next" dev -p "$WEB_PORT"

wait_http() {
  local url=$1
  local i=0
  while [[ "$i" -lt 180 ]]; do
    if curl -fsS -o /dev/null "$url"; then
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  die "Timed out waiting for ${url} (see ${ROOT}/api.log and ${ROOT}/web.log)"
}

wait_http "${API_URL}/docs"
wait_http "${WEB_URL}/"

if [[ "${NO_OPEN:-}" != "1" ]]; then
  open "$WEB_URL"
fi

echo "Dashboard: ${WEB_URL}"
echo "API docs: ${API_URL}/docs"
echo "Owner token file: ${ROOT}/.env"
echo "Stop with: ${ROOT}/stop.sh"
