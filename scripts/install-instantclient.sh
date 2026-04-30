#!/usr/bin/env bash
# Downloads Oracle Instant Client (Basic Light) into ./third_party/.
#
# Required for python-oracledb in THICK mode (ORACLE_CLIENT_MODE=thick).
# Skip this script if you're happy with thin mode — but thick is the default
# in this project's .env.example for parity with the original Oracle stack.
#
# Idempotent: skips if any third_party/instantclient_*/genezi[.exe] exists.
# Pass --force to reinstall.
# Optional --version <ver> + --slug <NNN0000> override the default 23.6 build.
#
# Auto-detects platform via uname (Linux x64, macOS arm64, macOS x64).
# For Windows use scripts/install-instantclient.ps1 instead.
#
# Requires curl + unzip.
#
# Usage:
#   ./scripts/install-instantclient.sh
#   ./scripts/install-instantclient.sh --force
#   ./scripts/install-instantclient.sh --version 23.6.0.24.10 --slug 2360000

set -euo pipefail

DEFAULT_VERSION="23.6.0.24.10"
DEFAULT_SLUG="2360000"

FORCE=0
VERSION="$DEFAULT_VERSION"
SLUG="$DEFAULT_SLUG"

while [ $# -gt 0 ]; do
    case "$1" in
        --force)   FORCE=1; shift ;;
        --version) VERSION="$2"; shift 2 ;;
        --slug)    SLUG="$2"; shift 2 ;;
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
THIRD_PARTY_DIR="$REPO_ROOT/third_party"

# Detect platform.
KERNEL="$(uname -s)"
ARCH="$(uname -m)"
case "$KERNEL" in
    Linux)
        case "$ARCH" in
            x86_64) PLATFORM_DIR=linux; PLATFORM_NAME=linux.x64 ;;
            *) echo "Unsupported Linux arch: $ARCH" >&2; exit 1 ;;
        esac
        ;;
    Darwin)
        case "$ARCH" in
            arm64)  PLATFORM_DIR=mac; PLATFORM_NAME=macos.arm64 ;;
            x86_64) PLATFORM_DIR=mac; PLATFORM_NAME=macos.x64 ;;
            *) echo "Unsupported macOS arch: $ARCH" >&2; exit 1 ;;
        esac
        ;;
    *)
        echo "Unsupported kernel: $KERNEL. Use install-instantclient.ps1 on Windows." >&2
        exit 1
        ;;
esac

URL="https://download.oracle.com/otn_software/$PLATFORM_DIR/instantclient/$SLUG/instantclient-basiclite-$PLATFORM_NAME-$VERSION.zip"

echo "==> nl2sql-agent: Oracle Instant Client (Basic Light) bootstrap"
echo "    Repo root : $REPO_ROOT"
echo "    Target    : $THIRD_PARTY_DIR"
echo "    Source    : $URL"
echo "    Platform  : $PLATFORM_NAME"

# Idempotency: bail if any instantclient_* with genezi already exists.
if [ "$FORCE" -eq 0 ]; then
    shopt -s nullglob
    for d in "$THIRD_PARTY_DIR"/instantclient_*; do
        if [ -d "$d" ] && { [ -f "$d/genezi" ] || [ -f "$d/genezi.exe" ]; }; then
            echo "==> Instant Client already installed at $d (use --force to reinstall)."
            echo "    Set in your .env:"
            echo "      ORACLE_CLIENT_MODE=thick"
            echo "      ORACLE_CLIENT_LIB_DIR=$d"
            exit 0
        fi
    done
    shopt -u nullglob
fi

mkdir -p "$THIRD_PARTY_DIR"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
ZIP_FILE="$TMP_DIR/instantclient.zip"

echo "==> Downloading…"
curl -fL --progress-bar "$URL" -o "$ZIP_FILE"

if [ "$FORCE" -eq 1 ]; then
    echo "==> --force: removing existing instantclient_* folders"
    rm -rf "$THIRD_PARTY_DIR"/instantclient_*
fi

echo "==> Extracting into $THIRD_PARTY_DIR…"
unzip -q "$ZIP_FILE" -d "$THIRD_PARTY_DIR"

EXTRACTED="$(find "$THIRD_PARTY_DIR" -maxdepth 1 -type d -name 'instantclient_*' | sort -r | head -1)"
if [ -z "$EXTRACTED" ]; then
    echo "==> ERROR: extraction did not produce an instantclient_* folder" >&2
    exit 1
fi

echo "==> Done."
echo "    Set in your .env:"
echo "      ORACLE_CLIENT_MODE=thick"
echo "      ORACLE_CLIENT_LIB_DIR=$EXTRACTED"
