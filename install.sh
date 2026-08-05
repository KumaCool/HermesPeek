#!/bin/sh
set -eu

INSTALLER_VERSION="0.1.0"
RELEASE_CHANNEL="${HERMES_PEEK_CHANNEL:-release}"
NON_INTERACTIVE=false
DRY_RUN=false

usage() {
    cat <<EOF
Usage: install.sh [--version] [--non-interactive] [--dry-run]
EOF
}

for argument in "$@"; do
    case "$argument" in
        --version)
            printf 'HermesPeek installer %s\n' "$INSTALLER_VERSION"
            exit 0
            ;;
        --non-interactive) NON_INTERACTIVE=true ;;
        --dry-run) DRY_RUN=true ;;
        --help|-h) usage; exit 0 ;;
        *) printf 'error: unknown option: %s\n' "$argument" >&2; usage >&2; exit 2 ;;
    esac
done

if [ "$DRY_RUN" = true ]; then
    printf 'HermesPeek install plan: channel=%s version=%s\n' "$RELEASE_CHANNEL" "$INSTALLER_VERSION"
    if [ "$NON_INTERACTIVE" = true ]; then
        printf 'After verified package installation: hermes-peek setup --non-interactive\n'
    else
        printf 'After verified package installation: hermes-peek setup\n'
    fi
    exit 0
fi

UNAME_COMMAND="${HERMES_PEEK_UNAME:-}"
if [ -z "$UNAME_COMMAND" ]; then
    UNAME_COMMAND=$(uname -s)
fi
if [ "$UNAME_COMMAND" != "Linux" ]; then
    printf 'UNSUPPORTED: Linux with a systemd user manager is required\n' >&2
    exit 1
fi

SYSTEMCTL_COMMAND="${HERMES_PEEK_SYSTEMCTL:-systemctl}"
if ! "$SYSTEMCTL_COMMAND" --user show-environment >/dev/null 2>&1; then
    printf 'PENDING_BACKEND: a running systemd user manager is required\n' >&2
    exit 1
fi

HERMES_COMMAND="${HERMES_PEEK_HERMES:-hermes}"
if ! "$HERMES_COMMAND" --version >/dev/null 2>&1; then
    printf 'error: Hermes Agent is required; install and configure Hermes first\n' >&2
    exit 1
fi
PYTHON_COMMAND="${HERMES_PEEK_PYTHON:-python3}"
if ! "$PYTHON_COMMAND" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
    printf 'error: supported Python 3.11 or newer is required\n' >&2
    exit 1
fi
UV_COMMAND="${HERMES_PEEK_UV:-uv}"
if ! "$UV_COMMAND" --version >/dev/null 2>&1; then
    printf 'error: uv is required; install it from https://docs.astral.sh/uv/\n' >&2
    exit 1
fi

ASSET="hermes_peek-${INSTALLER_VERSION}-py3-none-any.whl"
RELEASE_BASE_URL="${HERMES_PEEK_RELEASE_BASE_URL:-https://github.com/KumaCool/HermesPeek/releases/download/v${INSTALLER_VERSION}}"
CURL_COMMAND="${HERMES_PEEK_CURL:-curl}"
INSTALL_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/hermes-peek"
INSTALL_BIN="${HERMES_PEEK_INSTALL_BIN:-$INSTALL_ROOT/bin}"
export UV_TOOL_DIR="$INSTALL_ROOT"
export UV_TOOL_BIN_DIR="$INSTALL_BIN"
PEEK_COMMAND="${HERMES_PEEK_BIN:-$INSTALL_BIN/hermes-peek}"

if [ -x "$PEEK_COMMAND" ] && [ "$($PEEK_COMMAND --version 2>/dev/null || true)" = "hermes-peek $INSTALLER_VERSION" ]; then
    printf 'HermesPeek %s is already installed; keeping existing installation\n' "$INSTALLER_VERSION"
    exit 0
fi

WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/hermes-peek-install.XXXXXX")
trap 'rm -rf "$WORK_DIR"' EXIT HUP INT TERM

if ! "$CURL_COMMAND" -fsSL "$RELEASE_BASE_URL/$ASSET" -o "$WORK_DIR/$ASSET"; then
    printf 'error: failed to download fixed release asset; nothing was installed\n' >&2
    exit 1
fi
if ! "$CURL_COMMAND" -fsSL "$RELEASE_BASE_URL/SHA256SUMS" -o "$WORK_DIR/SHA256SUMS"; then
    printf 'error: failed to download SHA256SUMS; nothing was installed\n' >&2
    exit 1
fi
if ! (cd "$WORK_DIR" && sha256sum -c SHA256SUMS --ignore-missing >/dev/null 2>&1) || \
   ! grep -F "  $ASSET" "$WORK_DIR/SHA256SUMS" >/dev/null 2>&1; then
    printf 'error: release checksum verification failed; nothing was installed\n' >&2
    exit 1
fi

"$UV_COMMAND" tool install --python "$PYTHON_COMMAND" "$WORK_DIR/$ASSET"
if [ "$NON_INTERACTIVE" = true ]; then
    printf 'Non-interactive mode selected; setup still validates required configuration without inventing values.\n'
fi
"$PEEK_COMMAND" setup
printf 'HermesPeek %s installed successfully\n' "$INSTALLER_VERSION"
