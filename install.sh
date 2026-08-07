#!/bin/sh
set -eu

INSTALLER_VERSION="0.2.14"
RELEASE_CHANNEL="${HERMES_PEEK_CHANNEL:-release}"
NON_INTERACTIVE=false
DRY_RUN=false
SETUP_ARGUMENTS=false

usage() {
    cat <<EOF
Usage: install.sh [--version] [--dry-run] [hermes-peek setup options]

Without setup options, the installer opens an interactive setup wizard.
Setup options are passed through to hermes-peek setup; use -- to separate them.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --version)
            printf 'HermesPeek installer %s\n' "$INSTALLER_VERSION"
            exit 0
            ;;
        --non-interactive) NON_INTERACTIVE=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help|-h) usage; exit 0 ;;
        --)
            SETUP_ARGUMENTS=true
            shift
            break
            ;;
        --allowed-root|--external-url|--telegram-bot-username|--telegram-mini-app-short-name|--telegram-mini-app-mode|--telegram-env|--configure-telegram-menu|--hermes-home|--no-activate|--plan)
            SETUP_ARGUMENTS=true
            break
            ;;
        *) printf 'error: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

if [ "$DRY_RUN" = true ]; then
    printf 'HermesPeek install plan: channel=%s version=%s\n' "$RELEASE_CHANNEL" "$INSTALLER_VERSION"
    if [ "$NON_INTERACTIVE" = true ] || [ "$SETUP_ARGUMENTS" = true ]; then
        printf 'After verified package installation: hermes-peek setup <provided arguments>\n'
    else
        printf 'After verified package installation: hermes-peek setup\n'
    fi
    exit 0
fi

printf 'Checking installation requirements...\n'
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

ASSET="hermes_peek-0.2.14-py3-none-any.whl"
RELEASE_BASE_URL="${HERMES_PEEK_RELEASE_BASE_URL:-https://github.com/KumaCool/HermesPeek/releases/download/v${INSTALLER_VERSION}}"
CURL_COMMAND="${HERMES_PEEK_CURL:-curl}"
INSTALL_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/hermes-peek"
INSTALL_BIN="${HERMES_PEEK_INSTALL_BIN:-$INSTALL_ROOT/bin}"
COMMAND_DIR="${HERMES_PEEK_COMMAND_DIR:-$HOME/.local/bin}"
COMMAND_LINK="${HERMES_PEEK_COMMAND_LINK:-$COMMAND_DIR/hermes-peek}"
INSTALL_METADATA="$INSTALL_ROOT/install-metadata.json"
export UV_TOOL_DIR="$INSTALL_ROOT"
export UV_TOOL_BIN_DIR="$INSTALL_BIN"
PEEK_COMMAND="${HERMES_PEEK_BIN:-$INSTALL_BIN/hermes-peek}"

if [ -x "$PEEK_COMMAND" ] && [ "$($PEEK_COMMAND --version 2>/dev/null || true)" = "hermes-peek $INSTALLER_VERSION" ]; then
    mkdir -p "$COMMAND_DIR"
    if [ -e "$COMMAND_LINK" ] && [ ! -L "$COMMAND_LINK" ]; then
        printf 'error: refusing to replace non-symlink command: %s\n' "$COMMAND_LINK" >&2
        exit 1
    fi
    ln -sfn "$PEEK_COMMAND" "$COMMAND_LINK"
    printf '{"schema_version":1,"install_root":"%s","executable":"%s","command_link":"%s"}\n' \
        "$INSTALL_ROOT" "$PEEK_COMMAND" "$COMMAND_LINK" > "$INSTALL_METADATA"
    chmod 600 "$INSTALL_METADATA"
    printf 'HermesPeek %s is already installed; repaired command entry %s\n' "$INSTALLER_VERSION" "$COMMAND_LINK"
    if [ "$NON_INTERACTIVE" = false ] && [ "$SETUP_ARGUMENTS" = false ]; then
        exit 0
    fi
    PATH="$INSTALL_BIN:$COMMAND_DIR:$PATH"; export PATH
    "$PEEK_COMMAND" setup "$@" </dev/null
    exit $?
fi

WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/hermes-peek-install.XXXXXX")
trap 'rm -rf "$WORK_DIR"' EXIT HUP INT TERM

printf 'Downloading HermesPeek %s...\n' "$INSTALLER_VERSION"
if ! "$CURL_COMMAND" -fsSL "$RELEASE_BASE_URL/$ASSET" -o "$WORK_DIR/$ASSET"; then
    printf 'error: failed to download fixed release asset; nothing was installed\n' >&2
    exit 1
fi
if ! "$CURL_COMMAND" -fsSL "$RELEASE_BASE_URL/SHA256SUMS" -o "$WORK_DIR/SHA256SUMS"; then
    printf 'error: failed to download SHA256SUMS; nothing was installed\n' >&2
    exit 1
fi
printf 'Verifying package...\n'
if ! (cd "$WORK_DIR" && sha256sum -c SHA256SUMS --ignore-missing >/dev/null 2>&1) || \
   ! grep -F "  $ASSET" "$WORK_DIR/SHA256SUMS" >/dev/null 2>&1; then
    printf 'error: release checksum verification failed; nothing was installed\n' >&2
    exit 1
fi

printf 'Installing HermesPeek CLI...\n'
"$UV_COMMAND" tool install --force --python "$PYTHON_COMMAND" "$WORK_DIR/$ASSET"
INSTALLED_VERSION=$($PEEK_COMMAND --version 2>/dev/null || true)
if [ "$INSTALLED_VERSION" != "hermes-peek $INSTALLER_VERSION" ]; then
    printf 'error: installed HermesPeek version verification failed (expected %s)\n' "$INSTALLER_VERSION" >&2
    exit 1
fi
mkdir -p "$COMMAND_DIR"
if [ -e "$COMMAND_LINK" ] && [ ! -L "$COMMAND_LINK" ]; then
    printf 'error: refusing to replace non-symlink command: %s\n' "$COMMAND_LINK" >&2
    exit 1
fi
ln -sfn "$PEEK_COMMAND" "$COMMAND_LINK"
if [ "$($COMMAND_LINK --version 2>/dev/null || true)" != "hermes-peek $INSTALLER_VERSION" ]; then
    printf 'error: stable hermes-peek command verification failed\n' >&2
    exit 1
fi
printf '{"schema_version":1,"install_root":"%s","executable":"%s","command_link":"%s"}\n' \
    "$INSTALL_ROOT" "$PEEK_COMMAND" "$COMMAND_LINK" > "$INSTALL_METADATA"
chmod 600 "$INSTALL_METADATA"
case ":$PATH:" in
    *":$COMMAND_DIR:"*) : ;;
    *) printf 'NOTE: add %s to PATH, then open a new shell to use hermes-peek directly.\n' "$COMMAND_DIR" ;;
esac
# Keep the freshly installed uv tool and its stable user command discoverable
# while setup writes the service unit.
PATH="$INSTALL_BIN:$COMMAND_DIR:$PATH"
export PATH
if [ "$NON_INTERACTIVE" = true ]; then
    printf 'Non-interactive mode selected; setup still validates required configuration without inventing values.\n'
fi
if [ "$NON_INTERACTIVE" = true ] || [ "$SETUP_ARGUMENTS" = true ]; then
    # Explicit arguments select non-interactive setup. Keep stdin away from the
    # curl pipe so an incomplete parameter set fails instead of prompting.
    "$PEEK_COMMAND" setup "$@" </dev/null
else
    if ! (exec </dev/tty) 2>/dev/null; then
        printf 'error: interactive setup requires a terminal; provide setup arguments instead\n' >&2
        exit 1
    fi
    # curl | sh feeds this script's stdin. Re-open the user's terminal for the
    # setup wizard so the documented one-command install remains interactive.
    "$PEEK_COMMAND" setup </dev/tty
fi
