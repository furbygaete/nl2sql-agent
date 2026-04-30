#!/usr/bin/env bash
# Downloads Oracle SQLcl into ./vendor/sqlcl/.
#
# Idempotent: skips if vendor/sqlcl/bin/sql exists. Pass --force to reinstall.
# Optional --version <ver> overrides the "latest" URL.
#
# Requires curl + unzip + Java (JRE 17+). The script does NOT install Java.
#
# Usage:
#   ./scripts/install-sqlcl.sh
#   ./scripts/install-sqlcl.sh --force
#   ./scripts/install-sqlcl.sh --version 23.4.0.023.2321

set -euo pipefail

FORCE=0
VERSION="latest"

while [ $# -gt 0 ]; do
    case "$1" in
        --force)   FORCE=1; shift ;;
        --version) VERSION="$2"; shift 2 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# //; s/^#$//'
            exit 0
            ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

# Resolve repo root (script lives in scripts/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENDOR_DIR="$REPO_ROOT/vendor"
SQLCL_DIR="$VENDOR_DIR/sqlcl"
SQL_BIN="$SQLCL_DIR/bin/sql"

if [ "$VERSION" = "latest" ]; then
    URL="https://download.oracle.com/otn_software/java/sqldeveloper/sqlcl-latest.zip"
else
    URL="https://download.oracle.com/otn_software/java/sqldeveloper/sqlcl-$VERSION.zip"
fi

echo "==> nl2sql-agent: SQLcl bootstrap"
echo "    Repo root : $REPO_ROOT"
echo "    Target    : $SQLCL_DIR"
echo "    Source    : $URL"

if [ "$FORCE" -eq 0 ] && [ -x "$SQL_BIN" ]; then
    echo "==> SQLcl already installed at $SQL_BIN (use --force to reinstall)."
    echo
    echo "Next: set this in your .env"
    echo "    SQLCL_PATH=vendor/sqlcl/bin/sql"
    exit 0
fi

# Java sanity check.
if ! command -v java >/dev/null 2>&1; then
    echo "WARNING: java is not on PATH. SQLcl needs JRE 17+ to run." >&2
    echo "         Install OpenJDK / Adoptium and re-run this script." >&2
else
    java -version 2>&1 | head -n 1 | sed 's/^/    Java      : /'
fi

# Tooling sanity.
for cmd in curl unzip; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "ERROR: '$cmd' is required but not installed." >&2
        exit 1
    fi
done

if [ "$FORCE" -eq 1 ] && [ -d "$SQLCL_DIR" ]; then
    echo "==> --force: removing existing $SQLCL_DIR"
    rm -rf "$SQLCL_DIR"
fi

mkdir -p "$VENDOR_DIR"

TMP_ZIP="$(mktemp -t sqlcl-XXXXXXXX.zip)"
TMP_EXTRACT="$(mktemp -d -t sqlcl-extract-XXXXXXXX)"
cleanup() { rm -f "$TMP_ZIP"; rm -rf "$TMP_EXTRACT"; }
trap cleanup EXIT

echo "==> Downloading SQLcl ..."
curl -fL --progress-bar -o "$TMP_ZIP" "$URL"
SIZE_MB=$(du -m "$TMP_ZIP" | cut -f1)
echo "    Downloaded ${SIZE_MB} MB to $TMP_ZIP"

echo "==> Extracting ..."
unzip -q "$TMP_ZIP" -d "$TMP_EXTRACT"

# Oracle's zip nests a single 'sqlcl' folder at the top level.
INNER_DIR="$TMP_EXTRACT/sqlcl"
if [ ! -d "$INNER_DIR" ]; then
    echo "ERROR: Unexpected zip layout: '$INNER_DIR' not found." >&2
    exit 1
fi

# Move the inner contents into vendor/sqlcl/.
mv "$INNER_DIR" "$SQLCL_DIR"

# Make sure the launcher is executable (the zip preserves bits, but be safe).
chmod +x "$SQL_BIN" 2>/dev/null || true

if [ ! -x "$SQL_BIN" ] && [ ! -f "$SQL_BIN" ]; then
    echo "ERROR: install completed but $SQL_BIN is missing. Inspect $SQLCL_DIR." >&2
    exit 1
fi

echo
echo "==> SQLcl installed."
echo "    Binary    : $SQL_BIN"
echo
echo "Next: set these in your .env"
echo "    SQLCL_PATH=vendor/sqlcl/bin/sql"
echo "    SQLCL_USER_DIR=.sqlcl"
echo "    SQLCL_CONNECTIONS=[name,user/password@host:port/service]"
