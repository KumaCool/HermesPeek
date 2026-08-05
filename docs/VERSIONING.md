# Versioning and releases

HermesPeek uses [Semantic Versioning](https://semver.org/):

```text
MAJOR.MINOR.PATCH
```

- **MAJOR**: incompatible CLI, configuration, API, Registry, integration, or lifecycle changes.
- **MINOR**: backward-compatible features and supported preview capabilities.
- **PATCH**: backward-compatible bug fixes, security hardening, and documentation corrections.

Before `1.0.0`, a minor release may contain compatibility changes appropriate for an early-stage project. Such changes must be called out prominently in the changelog and release notes.

## Sources of the version

The release version is stored in:

- `pyproject.toml` under `[project].version`;
- `src/hermes_peek/__init__.py` as `__version__`.

Both values must match the Git tag without its `v` prefix. For example, tag `v0.2.0` corresponds to version `0.2.0`.

## Release checklist

1. Start from a clean `main` branch synchronized with `origin/main`.
2. Choose the next Semantic Version.
3. Update both version sources.
4. Move relevant entries from `Unreleased` to a dated section in `CHANGELOG.md`.
5. Verify README links, packaging metadata, and sensitive-data scans.
6. Run the complete test and build gate.
   Build the upload set with `uv run python scripts/build_release_assets.py --output dist/release`, then verify it with `uv run python scripts/verify_release_assets.py dist/release --tag v<version>`.
7. Commit the release metadata.
8. Create an annotated tag named `v<version>`.
9. Push `main` and the tag.
10. Create a GitHub Release from that exact tag and use the changelog section as release notes.
11. Verify the remote tag and published release assets.

Do not move or recreate an existing release tag. Publish a new patch version if a released artifact needs correction.

## Minimum release gate

```bash
uv sync --locked
uv run pytest
uv run python -m compileall -q src integrations tests
uv build
uv run python scripts/build_release_assets.py --output dist/release
uv run python scripts/verify_release_assets.py dist/release
uv run python scripts/offline_linux_acceptance.py --assets dist/release --root .acceptance
```

A release must not be described as verified if this gate fails. Any known failure must either be fixed before tagging or explicitly approved and documented as a release blocker waiver.
