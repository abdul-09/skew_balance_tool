# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project intends to follow [Semantic Versioning](https://semver.org/)
once it has a tagged release.

## [Unreleased]

### Added

- GitHub Actions CI (`.github/workflows/ci.yml`): lint (ruff), type-check
  (mypy), and tests (pytest, Python 3.10 and 3.12) on every push and PR.
- Committed, pinned dependency lockfiles (`requirements/dev.txt`,
  `requirements/postgres.txt`, `requirements/redis.txt`), a `lockfile-check`
  CI job that fails on drift from `pyproject.toml`, upper bounds on the
  `postgres`/`redis` optional dependencies, and a Dependabot config for
  weekly `pip` and `github-actions` update PRs.
- `dependency-audit` CI job (`pip-audit` against all three lockfiles).
- Construction-time validation of `SqlEventSource`'s `table`/`entity_column`/
  `timestamp_column`/`value_column` fields, closing a SQL-identifier
  injection point where those fields were interpolated directly into query
  text.
- `build` CI job (builds the sdist/wheel, validates packaging metadata with
  `twine check`) and a `publish` job that publishes to PyPI via Trusted
  Publishing (OIDC) when a `v*` tag is pushed. Pip dependency caching added
  to every job.
- Logging in `MaterializationJob.run()`'s batch loop (run start/summary at
  `INFO`, unknown-value entities at `WARNING`), via a standard
  `logging.getLogger(__name__)` logger that the package never configures
  itself.
- `CONTRIBUTING.md`, `.env.example`, `Dockerfile`, and a devcontainer config.

### Fixed

- `cli.main()`'s `stdout` parameter was typed `io.TextIOBase`, which
  `sys.stdout` doesn't satisfy under mypy; retyped as `typing.TextIO`.
- `pyproject.toml`'s `license = { text = "MIT" }` (deprecated table form,
  warns on every build) switched to the SPDX string form `license = "MIT"`.

## [0.1.0] - 2026-06-20

Initial implementation.

### Added

- `FeatureDefinition` / `FeatureRegistry`: the core primitive - one
  definition, with a `reduce()` that both the training and serving paths
  call, so they can't disagree.
- Offline path: `EventSource` protocol, `InMemoryEventSource`, and
  `OfflineStore` for point-in-time training sets.
- Online path: `OnlineStore` (in-memory) and the shared no-skew proof
  between training and serving values.
- `SqlEventSource`: a Postgres/SQLite-compatible `EventSource` over plain
  parameterized SQL.
- `RedisOnlineStore`: a Redis-backed `OnlineStore`.
- `MaterializationJob`: idempotent offline-to-online sync.
- `skewproof` CLI with a `demo` subcommand running the full
  define -> train -> materialize -> serve loop end to end.
