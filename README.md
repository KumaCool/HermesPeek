# HermesPeek

**English** | [简体中文](README.zh-CN.md)

> Secure, read-only previews of files created by [Hermes Agent](https://github.com/NousResearch/hermes-agent), delivered through Telegram.

HermesPeek is a small Python service and CLI for sharing the latest contents of selected local files in a protected Telegram Mini App. It is designed for personal workspaces, self-hosting, and contributors who want a clear, auditable alternative to copying files into chat.

HermesPeek does **not** edit, execute, upload, or delete files in the previewed workspace.

## What it does

```text
A file is created or changed
        ↓
HermesPeek validates the path and publishes a Preview
        ↓
Telegram receives an Open preview button
        ↓
The Mini App authenticates the Telegram user
        ↓
The Mini App reads the current file from disk
```

A Preview stores a reference to the file, not a static copy of its contents. Refreshing the page reads the current file again, subject to the same security checks. If the file is deleted, moved outside an allowed root, or becomes unsafe, it is no longer readable.

## Features

- Explicit CLI publishing with opaque Preview IDs.
- Read-only previews for:
  - Markdown;
  - source code and plain text;
  - JSON, YAML, and TOML;
  - PNG, JPEG, GIF, and WebP images;
  - PDF;
  - restricted, sandboxed HTML.
- Telegram Mini App authentication using signed `initData`.
- Preview owner authorization and short-lived sessions.
- Telegram private-chat buttons and group/Topic Mini App Direct Links.
- Complete conversational delivery installs the repository-distributed `hermes-peek-preview` Skill, the `hermes_peek_send_preview` Plugin Tool, and the Preview service together. The dedicated Tool uses the current Telegram session route; `publish --notify` remains available for CLI and troubleshooting use. Skill and Tool discovery takes effect in a new Hermes session (and, for an active Gateway, after an operator-authorized restart).
- Optional Hermes plugin integration:
  - collects successful `write_file` and `patch` results;
  - adds an `Open preview` action to the final Hermes reply when the integration is installed and enabled.
- Safe path handling:
  - explicit allowed roots;
  - directory traversal and symlink-escape protection;
  - sensitive-file and sensitive-directory rejection;
  - file-size and type limits;
  - a fresh security check on every read.
- Filesystem Registry with atomic writes, expiry, revocation, and rollback-aware lifecycle management.
- Local health endpoint: `GET /healthz`.

## Security boundaries

HermesPeek is intended to be exposed only through an approved HTTPS endpoint. Do not expose it to the public Internet until you have reviewed the threat model and deployment configuration.

By default, do not use a whole home directory, `/`, a Hermes state directory, or a directory containing credentials as an allowed root.

The following are never appropriate preview inputs:

- `.env` files, tokens, cookies, passwords, private keys, and certificates;
- `.git`, `.ssh`, `.hermes`, browser profiles, caches, and dependency directories;
- files outside the configured allowed roots;
- files larger than the configured limit.

A Preview ID is not an authorization credential. Access still requires a valid Telegram identity and owner authorization. Do not put bot tokens, cookies, private keys, personal chat IDs, or machine-specific deployment data in the repository.

See [`docs/03-security.md`](docs/03-security.md) for the detailed security model.

## Requirements

- Python 3.11 or newer;
- [uv](https://docs.astral.sh/uv/);
- Linux, macOS, or Windows for local development;
- an HTTPS URL reachable by the Telegram client for Telegram Mini App use;
- a Telegram bot only if Telegram notifications or Mini App integration are required.

## Installation paths

HermesPeek v0.2.1 publishes a verified Linux Release payload set (`wheel`, `sdist`, and `SHA256SUMS`). The repository/tag is the single source for `install.sh`, which downloads and verifies the matching fixed Release wheel. The one-command lifecycle supports Linux with a running systemd user manager. macOS, Windows, and Linux without a systemd user manager remain `PENDING_BACKEND`.

The complete onboarding and security contract is in [`docs/08-one-click-ai-telegram-onboarding.md`](docs/08-one-click-ai-telegram-onboarding.md), lifecycle behavior is authoritative in [`docs/06-installation-uninstallation.md`](docs/06-installation-uninstallation.md), and rollout status is tracked in [`docs/plan/05-one-click-ai-telegram-onboarding-rollout.md`](docs/plan/05-one-click-ai-telegram-onboarding-rollout.md).

## Operator quickstart

> The `main` installer tracks the current stable Release, v0.2.1. It verifies the fixed wheel against the published `SHA256SUMS` before installing and does not use `sudo`. For a version-fixed installer source, replace `main` with `v0.2.1`.

### 1. Install and run the setup wizard

```bash
curl -fsSL https://raw.githubusercontent.com/KumaCool/HermesPeek/main/install.sh | sh
```

The installer uses POSIX `sh`, so it can be started from Fish, Bash, Zsh, or another shell. With no setup arguments it reopens the terminal for an interactive wizard. `setup` discovers Hermes profiles and asks for an approved preview workspace, a Telegram-reachable HTTPS origin, the bot username, and a local Secret file. It shows a redacted plan before confirmation. Never paste a Bot Token into chat, command arguments, or README examples.

For a non-interactive installation, pass setup arguments after `sh -s --`. They are forwarded to the same `hermes-peek setup` lifecycle and no prompt is opened:

```bash
curl -fsSL https://raw.githubusercontent.com/KumaCool/HermesPeek/main/install.sh | sh -s -- \
  --hermes-home "$HERMES_HOME" \
  --allowed-root /path/to/approved/workspace \
  --external-url https://preview.example.test \
  --telegram-bot-username <bot-username> \
  --telegram-env /path/to/restricted/secrets.env \
  --plan
```

Remove `--plan` only after reviewing the redacted plan. The installer does not invent missing setup values.

For a non-interactive environment, first provide all values and print a read-only plan:

```bash
uv run hermes-peek setup \
  --hermes-home "$HERMES_HOME" \
  --allowed-root /path/to/approved/workspace \
  --external-url https://preview.example.test \
  --telegram-bot-username <bot-username> \
  --telegram-env /path/to/restricted/secrets.env \
  --plan
```

Review the plan, then remove `--plan` to apply it. The user-only Secret file should contain `TELEGRAM_BOT_TOKEN=...`; never commit it.

### 2. Complete Hermes and Telegram configuration

1. Follow the [Hermes Telegram documentation](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram), enable Telegram, and add your Telegram user ID to allowed users. HermesPeek never broadens authorization automatically.
2. Private-chat Preview does not require a Main Mini App. Before using Direct Links in a group or Forum Topic, the bot owner must bind a Main Mini App to the same bot in BotFather; `setChatMenuButton` is not a substitute.
3. The HTTPS origin must be reachable from the actual Telegram client. Privacy Mode, BotFather, and network configuration remain separate owner actions or approvals.
4. After setup, follow its checklist for Gateway activation, then start a new Hermes session so it can discover the new Skill and Tool.

### 3. Verify real usability

```bash
uv run hermes-peek status --json
uv run hermes-peek doctor --json
```

Passing these checks proves installation/configuration readiness only. Final acceptance requires requesting a real Preview from a new Hermes session and opening it in the intended private chat, group, or Topic.

### 4. Upgrade, rollback, and uninstall

The current CLI has no public `upgrade` subcommand. To upgrade, check out/install a verified fixed version and run `setup --plan`/`setup` again; do not copy internal Plugin or Skill files. Roll back a committed setup with its transaction ID:

```bash
uv run hermes-peek rollback --hermes-home "$HERMES_HOME" <transaction-id>
```

The default uninstall removes HermesPeek integration resources while **retaining Preview data**:

```bash
uv run hermes-peek uninstall --hermes-home "$HERMES_HOME"
```

To permanently remove the Registry, spool, logs, journals, and backups, inspect the Purge plan first and then explicitly confirm it:

```bash
uv run hermes-peek uninstall --hermes-home "$HERMES_HOME" --purge --dry-run
uv run hermes-peek uninstall --hermes-home "$HERMES_HOME" --purge --yes
```

Purge never deletes original project files under an allowed root. See [Installation, upgrade, uninstall, and purge](docs/06-installation-uninstallation.md) for the complete retention matrix, deactivation failure behavior, and recovery guidance.

## Install with an AI agent

Copy the prompt below into an agent that has terminal access. AI-assisted installation does not waive approvals.

<!-- ai-install-prompt:start -->
```text
Help me install and verify HermesPeek from https://github.com/KumaCool/HermesPeek.

Before acting:
1. Read README.md, docs/08-one-click-ai-telegram-onboarding.md,
   docs/06-installation-uninstallation.md, AGENTS.md, the rollout status in
   docs/plan/05-one-click-ai-telegram-onboarding-rollout.md, and inspect the
   current GitHub Release assets. Treat those as authoritative sources, then
   perform read-only discovery of the actual host, Hermes profiles, service,
   Gateway, Telegram configuration, and missing inputs.
2. First output a redacted plan. Do not make any change until I approve every
   side effect. Obtain separate confirmation before changing a real Hermes
   profile or service, restarting Gateway, changing a Telegram menu, or making
   any HTTPS, port, firewall, proxy, Tailscale, certificate, or other network
   change.
3. Do not send or ask me to send a Telegram Bot Token, API key, password, or any
   Secret in chat. Read Secrets only from a restricted local file or through
   secure local input (not chat); never expose them in chat, command arguments,
   plans, or logs.
4. Inspect the v0.2.1 Release, confirm that it contains the matching wheel,
   sdist, and SHA256SUMS, then use the repository/tag installer and
   hermes-peek setup. Do not copy internal plugin/Skill files or invent another
   installation flow.
5. Verify and report three completion levels separately: (a) installation
   complete: CLI/profile/service checks pass; (b) Hermes loading complete: the
   intended profile, Gateway, new session, Skill, and Tool are live; and (c)
   Telegram acceptance complete: a real new-session Preview succeeds in the
   original private chat, group, or Topic. Never promote offline tests or an
   earlier level to a later one.
6. Finish with the redacted verification checklist and any pending owner-only
   BotFather, HTTPS, Gateway, or Telegram steps. Do not claim success for a
   check that was not run.
```
<!-- ai-install-prompt:end -->

## Install for development

Clone the repository and install the locked development environment:

```bash
git clone https://github.com/<your-account>/HermesPeek.git
cd HermesPeek
uv sync --locked
```

Run the CLI help to confirm the installation:

```bash
uv run hermes-peek --help
```

The project is not currently published as a PyPI package. For development, use `uv run` from the repository or install the built wheel into a separate environment.

## Local preview service

Choose a safe workspace containing files you intentionally want to preview. The allowed-root value is an environment-specific setting and must not be committed.

```bash
export HERMES_PEEK_ALLOWED_ROOTS="$PWD/example-workspace"
export HERMES_PEEK_STATE_DIR="$PWD/.hermes-peek-state"

uv run hermes-peek serve --host 127.0.0.1 --port 8765
```

The service listens on loopback only. Verify it from another terminal:

```bash
curl -fsS http://127.0.0.1:8765/healthz
```

Expected response:

```json
{"status":"ok","service":"hermes-peek"}
```

Open the project home page at <http://127.0.0.1:8765/>. A Preview must be published before it can be opened; the old `preview?path=...` direct-path workflow is not supported.

For multiple allowed roots, join paths with `:` on Linux/macOS and `;` on Windows.

## Publish a Preview from the CLI

Set an HTTPS base URL when the Preview will be opened by another device or by Telegram:

```bash
export HERMES_PEEK_EXTERNAL_BASE_URL="https://preview.example.test"
```

Publish one or more files. The entry file must be one of the published files:

```bash
uv run hermes-peek publish \
  README.md docs/03-security.md \
  --entry README.md \
  --title "HermesPeek documentation" \
  --owner <telegram-user-id>
```

The command prints JSON containing the opaque Preview ID and, when an external base URL is configured, its public HTTPS URL. It does not print the server's absolute file paths.

Inspect public metadata:

```bash
uv run hermes-peek inspect <preview-id>
```

Revoke a Preview when it should no longer be available:

```bash
uv run hermes-peek revoke <preview-id>
```

Revocation is idempotent. It does not delete the original workspace files.

## Send a Telegram notification

Telegram sending is optional. Configure the bot token through a secret environment file or the runtime environment; never place it in the command line, source code, or committed files.

```bash
export HERMES_PEEK_TELEGRAM_BOT_TOKEN="<bot-token>"
export HERMES_PEEK_TELEGRAM_BOT_USERNAME="<bot-username>"

uv run hermes-peek publish \
  README.md \
  --entry README.md \
  --title "HermesPeek README" \
  --owner <telegram-user-id> \
  --notify \
  --chat-id <chat-id> \
  --chat-type private
```

For a group or Forum Topic:

```bash
uv run hermes-peek publish \
  README.md \
  --entry README.md \
  --title "HermesPeek README" \
  --owner <telegram-user-id> \
  --notify \
  --chat-id <supergroup-chat-id> \
  --chat-type supergroup \
  --thread-id <topic-thread-id>
```

Private chats use a Telegram Web App button. Groups and Topics use a Telegram Mini App Direct Link. The Telegram client must be able to reach the configured HTTPS endpoint, for example through a private Tailscale network.

## Hermes integration

The optional integration is distributed in [`integrations/hermes/`](integrations/hermes/). It is best-effort: a preview failure must never prevent Hermes from delivering its normal answer.

The integration observes only successful file-writing tool calls and keeps collected paths scoped to the current Hermes session. It must not infer files from shell commands, timestamps, a Git diff, or the final answer.

### Offline integration checks

The repository includes tests using temporary directories, fake runners, and mock Telegram transports. These validate contracts without changing a real Hermes profile or sending real Telegram messages.

### Install into a Hermes profile

Lifecycle management is available through the CLI. First inspect the redacted plan; this command should not write files or start services:

```bash
uv run hermes-peek setup \
  --hermes-home "$HERMES_HOME" \
  --allowed-root /path/to/approved/workspace \
  --external-url https://preview.example.test \
  --telegram-bot-username <bot-username> \
  --plan
```

After reviewing the plan, run setup in the target environment:

```bash
uv run hermes-peek setup \
  --hermes-home "$HERMES_HOME" \
  --allowed-root /path/to/approved/workspace \
  --external-url https://preview.example.test \
  --telegram-bot-username <bot-username>
```

Use `--configure-telegram-menu` only when you explicitly want setup to change the bot menu. Telegram's first Main Mini App binding still requires the bot owner to configure it in BotFather; it cannot be safely automated by this repository alone.

Before setup, configure the Telegram Bot in Hermes, restrict allowed users, and prepare a Telegram-reachable HTTPS Origin. Private-chat Preview does not require a Main Mini App binding. Before using Preview in a group or Forum Topic, bind the same Bot's Main Mini App in BotFather. For Privacy Mode, optional short names, Gateway activation, and the first real Preview test, follow [`docs/08-one-click-ai-telegram-onboarding.md`](docs/08-one-click-ai-telegram-onboarding.md#4-telegram-complete-configuration).

Check the installation:

```bash
uv run hermes-peek status --json
uv run hermes-peek doctor
```

A real Hermes profile and Gateway are deployment targets, not test fixtures. Review the generated plan and obtain the required authorization before changing them or restarting the Gateway.

## Uninstall, rollback, and purge

The default uninstall removes HermesPeek integration resources while retaining Preview data:

```bash
uv run hermes-peek uninstall --hermes-home "$HERMES_HOME"
```

Inspect lifecycle state and diagnostics:

```bash
uv run hermes-peek status --json
uv run hermes-peek doctor
```

Rollback a committed setup transaction using its transaction ID:

```bash
uv run hermes-peek rollback \
  --hermes-home "$HERMES_HOME" \
  <transaction-id>
```

Purge is destructive. Use a disposable test state, review the deletion list first, and do not run it against production Preview data until you have confirmed the scope:

```bash
uv run hermes-peek uninstall \
  --hermes-home "$HERMES_HOME" \
  --purge \
  --dry-run

uv run hermes-peek uninstall \
  --hermes-home "$HERMES_HOME" \
  --purge \
  --yes
```

## Configuration reference

The most commonly used settings are environment variables:

| Variable | Required | Purpose | Default |
|---|---:|---|---|
| `HERMES_PEEK_ALLOWED_ROOTS` | yes | `os.pathsep`-separated directories that may be previewed | — |
| `HERMES_PEEK_STATE_DIR` | no | Registry, sessions, launch references, and logs | XDG state directory |
| `HERMES_PEEK_EXTERNAL_BASE_URL` | no | HTTPS origin used to build Preview URLs | — |
| `HERMES_PEEK_MAX_FILE_BYTES` | no | Maximum previewable file size | 2 MiB |
| `HERMES_PEEK_DEFAULT_TTL_SECONDS` | no | Preview lifetime | 7 days |
| `HERMES_PEEK_TELEGRAM_BOT_TOKEN` | for Telegram | Bot API credential | — |
| `HERMES_PEEK_TELEGRAM_BOT_USERNAME` | for Mini App | Bot username used for Direct Links | — |
| `HERMES_PEEK_TELEGRAM_MINI_APP_SHORT_NAME` | no | Optional named Mini App short name | — |
| `HERMES_PEEK_TELEGRAM_MINI_APP_MODE` | no | Mini App display mode | `compact` |
| `HERMES_PEEK_DEVELOPMENT` | no | Enables development-only behavior where supported | `false` |

For lifecycle-managed installations, `HERMES_PEEK_CONFIG_FILE` points to the generated non-secret configuration. Secret values remain in a separate runtime secret file.

## Development and verification

Run the test suite and quality checks locally:

```bash
uv sync --locked
uv run pytest
uv run python -m compileall -q src integrations tests
uv build
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pre-commit run --all-files
```

Tests are designed to be offline by default. They do not require real Telegram credentials, a real Hermes profile, or access to a recruitment/preview endpoint.

## Documentation

- [Changelog](CHANGELOG.md)
- [Versioning and releases](docs/VERSIONING.md)
- [Product decisions](docs/00-product-decisions.md)
- [Design and development plan](docs/01-design-development-plan.md)
- [Architecture](docs/02-architecture.md)
- [Security model](docs/03-security.md)
- [Hermes integration](docs/04-hermes-integration.md)
- [Operations](docs/05-operations.md)
- [Installation, upgrade, uninstall, and purge](docs/06-installation-uninstallation.md)
- [One-command install, AI-assisted install, and Telegram onboarding](docs/08-one-click-ai-telegram-onboarding.md)
- [Implementation task plan](docs/plan/01-implementation-task-plan.md)
- [Telegram Topic Mini App rollout](docs/plan/02-telegram-topic-mini-app-rollout.md)
- [Lifecycle setup/uninstall rollout](docs/plan/03-lifecycle-setup-uninstall-rollout.md)
- [One-command, AI, and Telegram onboarding rollout](docs/plan/05-one-click-ai-telegram-onboarding-rollout.md)

## Contributing

Before opening an issue or pull request:

1. Explain the user-visible behavior or security boundary being changed.
2. Add or update tests for behavior changes.
3. Keep the default test suite offline and deterministic.
4. Do not bypass allowed-root, Telegram authentication, owner authorization, or read-only boundaries.
5. Do not commit bot tokens, API keys, passwords, cookies, private keys, personal IDs, internal hostnames, or deployment secrets.
6. Include a security analysis for changes involving file access, authentication, Telegram actions, or network exposure.

Please keep pull requests focused on one change. Bug reports should include a safe reproduction, expected behavior, actual behavior, and relevant sanitized logs. Do not publish credentials or exploit details in a public issue.

## License

HermesPeek is distributed under the [MIT License](LICENSE).
