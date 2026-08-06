# Repository Agent Instructions

These rules apply to any Agent installing, upgrading, verifying, rolling back, or uninstalling HermesPeek.

## Authoritative sources and discovery

1. Read `README.md` or `README.zh-CN.md`, `docs/08-one-click-ai-telegram-onboarding.md`, `docs/06-installation-uninstallation.md`, and `docs/plan/05-one-click-ai-telegram-onboarding-rollout.md` before proposing installation work. Inspect the actual `install.sh`, CLI help, current Release assets, and current Hermes documentation when they affect the task.
2. Perform read-only live discovery before planning: identify the operating system and supported service backend, Hermes installation, candidate profiles, target profile, Gateway and service state, Telegram configuration status, HTTPS prerequisites, and missing user inputs. Never infer these from repository examples.
3. Output a redacted plan before execution. The plan must identify the target and scope, reads, writes, commands, external calls, service impact, validation, rollback, and unresolved blockers. It must contain no Secret or machine-specific value.

## Secrets and approvals

- Never ask the user to paste Secrets into chat. A Telegram Bot Token, API key, password, cookie, private key, certificate, or other credential may be read only from a restricted local file or secure local input. Do not put it in model/tool arguments, shell arguments, plans, output, logs, screenshots, or repository files.
- Disclose every side effect and wait for explicit approval before applying it. Cancellation means zero new side effects.
- A real Hermes profile change, service install/start/stop/restart, Gateway restart, Telegram menu or Bot API write, BotFather owner action, and every HTTPS, port, firewall, proxy, DNS, certificate, Tailscale, or other network change each require separate confirmation. Approval for repository development or offline tests does not approve any of them.
- Do not change another profile or unrelated Hermes, Telegram, approval, Gateway, or network configuration.

## Installation path

- Prefer the repository/tag `install.sh` and the public `hermes-peek setup` lifecycle. The `main` script tracks the current stable Release; a version tag pins the installer source. Do not copy internal Plugin, Skill, unit, or implementation files and do not invent a parallel installer.
- An installer entry is available only when its target Release contains the matching package and checksum assets. Until then, state that the entry is unavailable; use the checked-out repository and `uv run hermes-peek setup` only as a repository development rehearsal. Never present a guessed download or curl command as working.
- Start with a read-only/redacted setup plan. Use setup, upgrade, rollback, and uninstall through their supported lifecycle commands rather than manual replacement.

## Completion contract

Report these levels independently; a lower level never proves a higher one:

1. **Installation complete** — the intended CLI version, target profile resources, service state, `hermes-peek status --json`, and `hermes-peek doctor` have been checked on the target host.
2. **Hermes loading complete** — the intended real Hermes profile has the Skill and Plugin Tool enabled, the Gateway state has been checked, any required operator-authorized Gateway restart has occurred externally, and a new Hermes session discovers the capability.
3. **Telegram acceptance complete** — a real new-session request calls `hermes_peek_send_preview`, sends exactly one Preview to the original private chat, group, or Topic, and the authorized user opens it successfully. Offline tests, fake transports, `getMe`, a constructed URL, or menu configuration do not satisfy this level.

## Verification checklist

- [ ] Authoritative documents, implementation, Release assets, and live environment were inspected.
- [ ] Target profile, service backend, Gateway, Telegram, allowed root, and HTTPS prerequisites were discovered read-only.
- [ ] The user approved a redacted plan and every applicable side effect; separately gated changes have their own confirmations.
- [ ] Secrets came only from a restricted local file or secure local input and were absent from arguments and output.
- [ ] The supported installer/setup lifecycle was used; no internal files were copied.
- [ ] `hermes-peek status --json` and `hermes-peek doctor` were run and reported without overclaiming.
- [ ] Hermes loading was checked in the target profile and a new session, or marked pending.
- [ ] Real Telegram acceptance was performed in the original route, or marked pending.
- [ ] Remaining BotFather, HTTPS/network, Gateway, rollback, and owner actions are explicit and redacted.
