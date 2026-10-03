#!/usr/bin/env bash
# One-line macOS installer. Safe when piped (curl | bash) and when run from a checkout.
set -euo pipefail

DEFAULT_INSTALL_DIR="${HOME}/autonomous-company"
DEFAULT_REPO_URL="https://github.com/lalalaoneplus-dev/autonomous-company.git"
DEFAULT_TARBALL_URL="https://github.com/lalalaoneplus-dev/autonomous-company/archive/refs/heads/main.tar.gz"

die() {
  echo "$*" >&2
  exit 1
}

require_macos() {
  local sys
  sys="$(uname -s)"
  if [[ "$sys" != "Darwin" ]]; then
    die "This installer runs on macOS. Detected ${sys}."
  fi
}

looks_like_repo() {
  local d=$1
  [[ -f "${d}/.env.example" && -d "${d}/apps/api" && -d "${d}/apps/web" ]]
}

script_checkout() {
  local src="${BASH_SOURCE[0]:-}"
  case "$src" in
    ""|"-"|"bash"|/dev/fd/*|/proc/self/fd/*) return 1 ;;
  esac
  [[ -f "$src" ]] || return 1
  local dir
  dir="$(cd "$(dirname "$src")" && pwd)"
  looks_like_repo "$dir" || return 1
  printf '%s\n' "$dir"
}

ensure_uv() {
  export PATH="${HOME}/.local/bin:${PATH}"
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${PATH}"
  command -v uv >/dev/null 2>&1 || die "uv is required. It installs into ${HOME}/.local/bin."
}

ensure_api_venv() {
  if [[ ! -x "${REPO_DIR}/apps/api/.venv/bin/python" ]]; then
    uv venv --python 3.12 "${REPO_DIR}/apps/api/.venv"
  fi
}

node_arch() {
  case "$(uname -m)" in
    arm64) printf '%s\n' "arm64" ;;
    x86_64) printf '%s\n' "x64" ;;
    *) die "This installer needs arm64 or x86_64. Detected $(uname -m)." ;;
  esac
}

node_major() {
  node -p 'process.versions.node.split(".")[0]'
}

ensure_node() {
  export PATH="${REPO_DIR}/.node/bin:${HOME}/.local/bin:${PATH}"
  if command -v node >/dev/null 2>&1; then
    if [[ "$(node_major)" -ge 20 ]]; then
      return 0
    fi
  fi
  if [[ -x "${REPO_DIR}/.node/bin/node" ]]; then
    export PATH="${REPO_DIR}/.node/bin:${PATH}"
    if [[ "$(node_major)" -ge 20 ]]; then
      return 0
    fi
  fi

  local ver arch url tmp dest
  dest="${REPO_DIR}/.node"
  arch="$(node_arch)"
  ver="$(curl -fsSL https://nodejs.org/dist/index.json | "${REPO_DIR}/apps/api/.venv/bin/python" -c 'import json,sys
releases=json.load(sys.stdin)
for r in releases:
    if r.get("lts"):
        print(r["version"])
        break
')"
  [[ -n "$ver" ]] || die "Could not resolve the Node.js LTS version from nodejs.org."
  url="https://nodejs.org/dist/${ver}/node-${ver}-darwin-${arch}.tar.gz"
  tmp="$(mktemp)"
  mkdir -p "$dest"
  curl -fsSL "$url" -o "$tmp"
  tar -xzf "$tmp" -C "$dest" --strip-components=1
  rm -f "$tmp"
  export PATH="${dest}/bin:${PATH}"
  command -v node >/dev/null 2>&1 || die "Node.js is required."
  if [[ "$(node_major)" -lt 20 ]]; then
    die "Node.js 20 or newer is required."
  fi
}

pnpm_path() {
  export PNPM_HOME="${PNPM_HOME:-${HOME}/Library/pnpm}"
  export PATH="${REPO_DIR}/.node/bin:${HOME}/.local/bin:${PNPM_HOME}:${PNPM_HOME}/bin:${HOME}/.local/share/pnpm:${PATH}"
}

ensure_pnpm() {
  pnpm_path
  if command -v pnpm >/dev/null 2>&1; then
    return 0
  fi
  if command -v corepack >/dev/null 2>&1; then
    mkdir -p "${HOME}/.local/bin"
    corepack enable --install-directory "${HOME}/.local/bin" >/dev/null 2>&1 || true
    export PATH="${HOME}/.local/bin:${PATH}"
    corepack prepare pnpm@latest --activate >/dev/null 2>&1 || true
  fi
  pnpm_path
  if command -v pnpm >/dev/null 2>&1; then
    return 0
  fi
  curl -fsSL https://get.pnpm.io/install.sh | sh -
  pnpm_path
  command -v pnpm >/dev/null 2>&1 || die "pnpm is required."
}

sync_source() {
  local dest=$1
  local url="${REPO_URL:-$DEFAULT_REPO_URL}"
  local tarball="${TARBALL_URL:-$DEFAULT_TARBALL_URL}"

  mkdir -p "$dest"

  if [[ -d "$url" ]]; then
    url="$(cd "$url" && pwd)"
    dest="$(cd "$dest" && pwd)"
    if [[ "$url" == "$dest" ]]; then
      return 0
    fi
    /usr/bin/rsync -a \
      --exclude '.git/' \
      --exclude '.venv/' \
      --exclude 'node_modules/' \
      --exclude '.node/' \
      --exclude '.run/' \
      --exclude '.next/' \
      --exclude '__pycache__/' \
      --exclude '*.pyc' \
      --exclude '*.log' \
      --exclude '.env' \
      "${url}/" "${dest}/"
    return 0
  fi

  if command -v git >/dev/null 2>&1; then
    if [[ -d "${dest}/.git" ]]; then
      git -C "$dest" pull --ff-only
      return 0
    fi
    if [[ -z "$(ls -A "$dest" 2>/dev/null || true)" ]]; then
      git clone "$url" "$dest"
      return 0
    fi
    return 0
  fi

  local tmp inner
  tmp="$(mktemp -d)"
  curl -fsSL "$tarball" -o "${tmp}/src.tar.gz"
  tar -xzf "${tmp}/src.tar.gz" -C "$tmp"
  for inner in "$tmp"/*; do
    if [[ -d "$inner" ]]; then
      /usr/bin/rsync -a --exclude '.env' "${inner}/" "${dest}/"
      break
    fi
  done
  rm -rf "$tmp"
}

write_env_if_missing() {
  local env_file="${REPO_DIR}/.env"
  local token py
  if [[ -f "$env_file" ]]; then
    chmod 600 "$env_file" 2>/dev/null || true
    return 0
  fi
  cp "${REPO_DIR}/.env.example" "$env_file"
  py="${REPO_DIR}/apps/api/.venv/bin/python"
  [[ -x "$py" ]] || die "Python 3.12 virtualenv is missing in ${REPO_DIR}/apps/api/.venv."
  token="$("$py" -c 'import secrets; print(secrets.token_urlsafe(32))')"
  "$py" -c '
import pathlib, sys
path = pathlib.Path(sys.argv[1])
token = sys.argv[2]
lines = []
found = False
for line in path.read_text().splitlines(True):
    if line.startswith("OWNER_TOKEN="):
        nl = "\n" if line.endswith("\n") else ""
        lines.append("OWNER_TOKEN=" + token + nl)
        found = True
    else:
        lines.append(line)
if not found:
    lines.append("OWNER_TOKEN=" + token + "\n")
path.write_text("".join(lines))
' "$env_file" "$token"
  chmod 600 "$env_file"
}

require_macos

REPO_DIR=""
if checkout="$(script_checkout 2>/dev/null || true)" && [[ -n "${checkout}" && -z "${INSTALL_DIR:-}" ]]; then
  REPO_DIR="$checkout"
elif [[ -z "${INSTALL_DIR:-}" && -z "${REPO_URL:-}" ]] && looks_like_repo "$PWD"; then
  REPO_DIR="$PWD"
else
  REPO_DIR="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
  sync_source "$REPO_DIR"
fi

looks_like_repo "$REPO_DIR" || die "autonomous-company files were not found in ${REPO_DIR}"

ensure_uv
ensure_api_venv
ensure_node
ensure_pnpm

chmod +x "${REPO_DIR}/start.sh" "${REPO_DIR}/stop.sh" 2>/dev/null || true

write_env_if_missing

uv sync --python 3.12 --project "${REPO_DIR}/apps/api" --extra test
(
  cd "${REPO_DIR}/apps/api"
  uv run alembic upgrade head
)
(
  cd "${REPO_DIR}/apps/web"
  pnpm install
)

if [[ "${NO_START:-}" != "1" ]]; then
  "${REPO_DIR}/start.sh"
else
  echo "Dashboard URL: http://127.0.0.1:${WEB_PORT:-3000}"
  echo "Start with: ${REPO_DIR}/start.sh"
  echo "Stop with: ${REPO_DIR}/stop.sh"
  echo "Owner token file: ${REPO_DIR}/.env"
fi
