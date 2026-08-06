# Changelog

All notable changes to HermesPeek are documented in this file.

The project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Release sections use the format recommended by [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.2.8] - 2026-08-07

### Changed

- Keep ordinary setup output human-readable: validate and apply directly, hide transaction JSON, and print the installed version once on success.
- Reserve `setup --plan` for an explicit read-only, redacted dry run.

### Fixed

- Package the Hermes Plugin as a self-contained runtime so Gateway Tool execution does not depend on installing HermesPeek into the Gateway virtual environment.
- Verify the installed Plugin runtime during setup, status, and doctor instead of treating file presence and loaded state as Tool readiness.
- Ignore runtime-generated `__pycache__` entries during installer-owned Plugin integrity checks.
- Probe split-DNS HTTPS origins through `systemd-resolved` while preserving TLS hostname verification.
- Use package-relative imports throughout the bundled Preview runtime, including registry and service modules.

## [0.2.7] - 2026-08-07

### Fixed

- Make the freshly installed CLI discoverable during setup even when its uv tool bin directory is not in the login-shell `PATH`.
- Resolve the active CLI executable safely when setup is launched by absolute path.

## [0.2.6] - 2026-08-07

### Fixed

- Defer external `/healthz` enforcement until after the local preview service starts.
- Roll back setup if the configured HTTPS origin still cannot reach the running service.

## [0.2.5] - 2026-08-07

### Fixed

- Treat the Hermes root as the real `default` profile and ignore its auxiliary `profiles/default` state directory.
- Report missing profile credentials separately from unsafe credential path types.

## [0.2.4] - 2026-08-07

### Fixed

- Force the installer to replace an existing HermesPeek tool environment during upgrades.
- Add a working `hermes-peek --version` command and verify the installed version before setup starts.

## [0.2.3] - 2026-08-07

### Fixed

- Removed the requirement for users to change permissions on the selected Hermes profile's Telegram credential file.
- HermesPeek now leaves external Hermes credential files unchanged while keeping its own credential copy restricted to owner-only access (`0600`).
- Symlinks and non-regular credential paths remain rejected.

## [0.2.2] - 2026-08-06

### Changed

- Make purge uninstall output an explicit human-readable success message.
- Automatically remove the CLI when it is managed by `uv tool`.

## [0.2.1] - 2026-08-06

### Changed

- Made the `hermes-peek-preview` Skill trigger on multilingual file-preview intent rather than Chinese-only example phrases, with aligned English and Chinese positive and near-miss examples.
- Changed the stable installer entry to the repository's `main/install.sh`; fixed-version installs use the corresponding repository tag.
- Reduced GitHub Release assets to the wheel, source distribution, and `SHA256SUMS`; the repository/tag remains the single source for `install.sh`.
- Sourced the FastAPI application version from the package version to prevent version drift.

## [0.2.0] - 2026-08-06

### Added

- Interactive, plan-first setup with profile discovery, HTTPS and Secret-file checks, and explicit activation control.
- Verified Linux one-command installer for systems with a systemd user manager.
- Reproducible Release assets (`wheel`, `sdist`, `install.sh`, and `SHA256SUMS`) with tag-only publication and offline fresh-home acceptance.
- AI-assisted installation contract and repository Agent guidance that keep Secrets out of chat and gate side effects.
- Structured Telegram onboarding diagnostics covering Bot identity, webhook state, allowed-user evidence, HTTPS health, and Mini App link readiness.
- Complete English and Simplified Chinese operator quickstarts for installation, Telegram configuration, verification, upgrade, rollback, uninstall, and purge.

### Security

- Telegram diagnostics distinguish verified evidence from inferred or pending BotFather and client acceptance state.
- Installer verifies fixed-version assets with SHA-256 before installation and refuses unsupported service backends before writing.
- Setup and AI workflows require redacted plans and separate confirmation for profile, service, Gateway, Telegram, and network side effects.

## [0.1.0] - 2026-08-05

### Added

- Secure filesystem Preview Registry using opaque IDs, expiry, and revocation.
- Explicit `publish`, `inspect`, `revoke`, and `serve` CLI commands.
- Read-only rendering for Markdown, source code, text, structured data, images, PDF, and sandboxed HTML.
- Telegram Mini App authentication, Preview owner authorization, and short-lived sessions.
- Telegram notifications for private chats, groups, and Forum Topics.
- Optional Hermes integration for collecting successful file-writing tool results and attaching an `Open preview` action to the final reply.
- Allowed-root enforcement, traversal and symlink-escape protection, sensitive-path rejection, file-size limits, and per-read revalidation.
- Transactional setup, status, diagnostics, rollback, uninstall, and guarded purge commands.
- systemd user-service support and private HTTPS deployment documentation.
- English and Simplified Chinese usage guides.

### Security

- Preview URLs do not expose absolute server paths.
- Telegram identity and owner checks remain required even when a Preview ID is known.
- HTML is sandboxed and sanitized; workspace access remains read-only.

[Unreleased]: https://github.com/KumaCool/HermesPeek/compare/v0.2.8...HEAD
[0.2.8]: https://github.com/KumaCool/HermesPeek/releases/tag/v0.2.8
[0.2.7]: https://github.com/KumaCool/HermesPeek/releases/tag/v0.2.7
[0.2.6]: https://github.com/KumaCool/HermesPeek/releases/tag/v0.2.6
[0.2.5]: https://github.com/KumaCool/HermesPeek/releases/tag/v0.2.5
[0.2.4]: https://github.com/KumaCool/HermesPeek/releases/tag/v0.2.4
[0.2.3]: https://github.com/KumaCool/HermesPeek/releases/tag/v0.2.3
[0.2.2]: https://github.com/KumaCool/HermesPeek/releases/tag/v0.2.2
[0.2.1]: https://github.com/KumaCool/HermesPeek/releases/tag/v0.2.1
[0.2.0]: https://github.com/KumaCool/HermesPeek/releases/tag/v0.2.0
[0.1.0]: https://github.com/KumaCool/HermesPeek/releases/tag/v0.1.0
