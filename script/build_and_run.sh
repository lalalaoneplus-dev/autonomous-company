#!/bin/zsh
set -eu

MODE="${1:-run}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="Autonomous Company"
APP_SUPPORT="$HOME/Library/Application Support/$APP_NAME"
RUNTIME_DIR="$APP_SUPPORT/Runtime"
BACKUP_DIR="$APP_SUPPORT/Backups"
LOG_DIR="$HOME/Library/Logs/$APP_NAME"
TOKEN_FILE="$APP_SUPPORT/owner-token"
INSTALLED_APP="$HOME/Applications/$APP_NAME.app"
DESKTOP_APP="$HOME/Desktop/$APP_NAME.app"
BUILD_DIR="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/autonomous-company.XXXXXX")"
STAGED_APP="$BUILD_DIR/$APP_NAME.app"
STAGED_RUNTIME="$BUILD_DIR/Runtime"
CONTENTS="$STAGED_APP/Contents"
ICONSET="$BUILD_DIR/AppIcon.iconset"

cleanup() {
  /bin/rm -rf "$BUILD_DIR"
}
trap cleanup EXIT

case "$MODE" in
  run|--verify|verify|--debug|debug|--logs|logs|--telemetry|telemetry) ;;
  *)
    print -u2 "usage: $0 [run|--verify|--debug|--logs|--telemetry]"
    exit 2
    ;;
esac

if [[ "$MODE" == "--logs" || "$MODE" == "logs" || "$MODE" == "--telemetry" || "$MODE" == "telemetry" ]]; then
  /bin/mkdir -p "$LOG_DIR"
  exec /usr/bin/tail -n 120 -F "$LOG_DIR/api.log" "$LOG_DIR/web.log"
fi

find_tool() {
  for candidate in "$@"; do
    [[ -x "$candidate" ]] && print -r -- "$candidate" && return 0
  done
  return 1
}

require_owned_app() {
  local path="$1"
  [[ -e "$path" || -L "$path" ]] || return 0
  if [[ -L "$path" ]]; then
    [[ "$(/usr/bin/readlink "$path")" == "$INSTALLED_APP" ]] || {
      print -u2 "refusing to replace unrelated Desktop item: $path"
      exit 1
    }
    return 0
  fi
  local bundle_id
  bundle_id="$(/usr/bin/plutil -extract CFBundleIdentifier raw -o - "$path/Contents/Info.plist" 2>/dev/null || true)"
  [[ "$bundle_id" == "com.nexuspivot.autonomous-company" ]] || {
    print -u2 "refusing to replace unrelated app: $path"
    exit 1
  }
}

UV="$(find_tool /opt/homebrew/bin/uv /usr/local/bin/uv "$HOME/.local/bin/uv")" || {
  print -u2 "uv is required"
  exit 1
}
PNPM="$(find_tool "$HOME/.local/bin/pnpm" /opt/homebrew/bin/pnpm /usr/local/bin/pnpm)" || {
  print -u2 "pnpm is required"
  exit 1
}

/bin/mkdir -p "$STAGED_RUNTIME/api" "$STAGED_RUNTIME/web" "$CONTENTS/MacOS" "$CONTENTS/Resources" "$ICONSET"
/usr/bin/ditto "$PROJECT_ROOT/apps/api/app" "$STAGED_RUNTIME/api/app"
/usr/bin/ditto "$PROJECT_ROOT/apps/api/alembic" "$STAGED_RUNTIME/api/alembic"
/bin/cp "$PROJECT_ROOT/apps/api/alembic.ini" "$PROJECT_ROOT/apps/api/pyproject.toml" "$PROJECT_ROOT/apps/api/uv.lock" "$STAGED_RUNTIME/api/"

# Stop our current app before reading or migrating its active SQLite database.
# If another process owns either service port, fail closed instead of copying a
# database that may still be receiving writes.
/usr/bin/osascript -e 'tell application id "com.nexuspivot.autonomous-company" to quit' 2>/dev/null || true
for attempt in {1..40}; do
  if ! /usr/sbin/lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1 && \
     ! /usr/sbin/lsof -nP -iTCP:3000 -sTCP:LISTEN >/dev/null 2>&1; then
    break
  fi
  /bin/sleep 0.25
done
if /usr/sbin/lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1 || \
   /usr/sbin/lsof -nP -iTCP:3000 -sTCP:LISTEN >/dev/null 2>&1; then
  print -u2 "refusing to snapshot an active database while API or dashboard is still listening"
  exit 1
fi

SOURCE_DATABASE="$PROJECT_ROOT/apps/api/autonomous_company.db"
ACTIVE_DATABASE="$RUNTIME_DIR/api/autonomous_company.db"
if [[ -f "$ACTIVE_DATABASE" ]]; then
  DATABASE_TO_INSTALL="$ACTIVE_DATABASE"
elif [[ -f "$SOURCE_DATABASE" ]]; then
  DATABASE_TO_INSTALL="$SOURCE_DATABASE"
else
  DATABASE_TO_INSTALL=""
fi
if [[ -n "$DATABASE_TO_INSTALL" ]]; then
  /bin/cp -p "$DATABASE_TO_INSTALL" "$STAGED_RUNTIME/api/autonomous_company.db"
else
  # Alembic creates the schema from an empty SQLite file on a clean checkout.
  /usr/bin/touch "$STAGED_RUNTIME/api/autonomous_company.db"
fi
/bin/chmod 600 "$STAGED_RUNTIME/api/autonomous_company.db"

"$UV" sync --project "$STAGED_RUNTIME/api" --frozen
(cd "$STAGED_RUNTIME/api" && DATABASE_URL="sqlite:///./autonomous_company.db" .venv/bin/python -m alembic upgrade head)

if [[ -e "$PROJECT_ROOT/apps/web/.next" ]]; then /bin/rm -R "$PROJECT_ROOT/apps/web/.next"; fi
(cd "$PROJECT_ROOT/apps/web" && NEXT_PUBLIC_API_URL="http://127.0.0.1:8000" "$PNPM" exec next build --webpack)
[[ -f "$PROJECT_ROOT/apps/web/.next/standalone/server.js" ]] || { print -u2 "standalone dashboard build is missing"; exit 1; }
/usr/bin/ditto "$PROJECT_ROOT/apps/web/.next/standalone" "$STAGED_RUNTIME/web"
/bin/mkdir -p "$STAGED_RUNTIME/web/.next"
/usr/bin/ditto "$PROJECT_ROOT/apps/web/.next/static" "$STAGED_RUNTIME/web/.next/static"

/bin/cp "$PROJECT_ROOT/tools/AutonomousCompanyLauncher-Info.plist" "$CONTENTS/Info.plist"
/usr/bin/xcrun swiftc -O \
  -framework AppKit \
  -framework WebKit \
  "$PROJECT_ROOT/tools/AutonomousCompanyLauncher.swift" \
  -o "$CONTENTS/MacOS/$APP_NAME"

/usr/bin/qlmanage -t -s 1024 -o "$BUILD_DIR" "$PROJECT_ROOT/desktop/AppIcon.svg" >/dev/null 2>&1
BASE_ICON="$BUILD_DIR/AppIcon.svg.png"
[[ -f "$BASE_ICON" ]] || { print -u2 "icon rendering failed"; exit 1; }
for spec in "16 icon_16x16.png" "32 icon_16x16@2x.png" "32 icon_32x32.png" "64 icon_32x32@2x.png" "128 icon_128x128.png" "256 icon_128x128@2x.png" "256 icon_256x256.png" "512 icon_256x256@2x.png" "512 icon_512x512.png" "1024 icon_512x512@2x.png"; do
  size="${spec%% *}"
  name="${spec#* }"
  /usr/bin/sips -z "$size" "$size" "$BASE_ICON" --out "$ICONSET/$name" >/dev/null
done
/usr/bin/iconutil -c icns "$ICONSET" -o "$CONTENTS/Resources/AppIcon.icns"
/usr/bin/plutil -lint "$CONTENTS/Info.plist" >/dev/null
/usr/bin/codesign --force --deep --sign - "$STAGED_APP" >/dev/null

require_owned_app "$INSTALLED_APP"
require_owned_app "$DESKTOP_APP"
/bin/mkdir -p "$APP_SUPPORT" "$BACKUP_DIR" "$LOG_DIR" "$HOME/Applications"
/bin/chmod 700 "$APP_SUPPORT" "$BACKUP_DIR" "$LOG_DIR"
if [[ ! -f "$TOKEN_FILE" ]]; then
  /usr/bin/openssl rand -hex 32 >"$TOKEN_FILE"
fi
/bin/chmod 600 "$TOKEN_FILE"
if [[ -n "$DATABASE_TO_INSTALL" ]]; then
  /bin/cp -p "$DATABASE_TO_INSTALL" "$BACKUP_DIR/autonomous_company-pre-desktop-install-$(/bin/date +%Y%m%dT%H%M%S).db"
fi
if [[ -e "$RUNTIME_DIR" ]]; then /bin/rm -rf "$RUNTIME_DIR"; fi
/usr/bin/ditto "$STAGED_RUNTIME" "$RUNTIME_DIR"
/bin/chmod 700 "$RUNTIME_DIR" "$RUNTIME_DIR/api" "$RUNTIME_DIR/web"

if [[ -e "$INSTALLED_APP" ]]; then /bin/rm -rf "$INSTALLED_APP"; fi
/usr/bin/ditto "$STAGED_APP" "$INSTALLED_APP"
/usr/bin/codesign --verify --deep --strict "$INSTALLED_APP"
if [[ ! -L "$DESKTOP_APP" ]]; then
  if [[ -e "$DESKTOP_APP" ]]; then /bin/rm -R "$DESKTOP_APP"; fi
  /bin/ln -s "$INSTALLED_APP" "$DESKTOP_APP"
fi

if [[ "$MODE" == "--debug" || "$MODE" == "debug" ]]; then
  exec /usr/bin/lldb -- "$INSTALLED_APP/Contents/MacOS/$APP_NAME"
fi

/usr/bin/open -n "$DESKTOP_APP"

if [[ "$MODE" == "--verify" || "$MODE" == "verify" ]]; then
  for attempt in {1..160}; do
    if /usr/bin/curl -fsS http://127.0.0.1:8000/ready >/dev/null 2>&1 && \
       /usr/bin/curl -fsS http://127.0.0.1:3000 2>/dev/null | /usr/bin/grep -q '<title>Autonomous Company</title>' && \
       /usr/bin/pgrep -f "$INSTALLED_APP/Contents/MacOS/$APP_NAME" >/dev/null; then
      print "Autonomous Company desktop launch verified"
      exit 0
    fi
    /bin/sleep 0.25
  done
  print -u2 "desktop launch did not become ready; inspect $LOG_DIR"
  exit 1
fi
