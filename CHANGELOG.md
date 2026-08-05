# Changelog

All notable changes to HermesPeek are documented in this file.

The project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Release sections use the format recommended by [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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

[Unreleased]: https://github.com/KumaCool/HermesPeek/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/KumaCool/HermesPeek/releases/tag/v0.1.0
