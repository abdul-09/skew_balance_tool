# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

Nothing yet.

## [0.1.0] - 2026-10-08

First release. No version of this project had been tagged before, so this entry
covers everything from the initial implementation up to the tag, rather than
splitting out work that was never released separately.

### Added

Core:

- `FeatureDefinition` / `FeatureRegistry`: the core primitive. One definition,
  with a `reduce()` that both the training and serving paths call, so they can't
  disagree.
- Offline path: `EventSource` protocol, `InMemoryEventSource`, and `OfflineStore`
  for point-in-time training sets.
- Online path: `OnlineStore` (in-memory) and the shared no-skew proof between
  training and serving values.
- `SqlEventSource`: a Postgres/SQLite-compatible `EventSource` over plain
  parameterized SQL.
- `RedisOnlineStore`: a Redis-backed `OnlineStore`.
- `MaterializationJob`: idempotent offline-to-online sync.
- `skewproof` CLI with a `demo` subcommand running the full
  define -> train -> materialize -> serve loop end to end.

Backends:

- `CsvEventSource`: a stdlib-only, file-backed `EventSource` for local
  development and onboarding without a database.
- `SqliteOnlineStore`: a `sqlite3`-backed `OnlineStore`. Durable serving with no
  server to run, sitting between the in-memory store and Redis.

CLI and operational tooling:

- `skewproof.config.load_registry()`: load a `FeatureRegistry` from a plain Python
  file, reusing the syntax the README's own example uses rather than inventing a
  config format.
- CLI subcommands `list`, `validate`, and `materialize`, all driven by `--config`.
- `skewproof.batch.BatchMaterializationJob`: materialize several features against
  one online store in one call, each with its own `EventSource`.
- `skewproof.backfill.BackfillJob`: replay one feature across a range of `as_of`
  instants, for incremental population or historical coverage auditing.
- `skewproof.doctor` / `skewproof doctor`: connectivity checks for the optional
  Postgres/Redis backends, keyed off the same env vars the integration tests use.
- `skewproof.serve` / `skewproof serve`: a minimal HTTP layer with
  `GET /healthz` (liveness), `GET /metrics` (request and error counters in
  Prometheus text format, hand-rolled rather than a client-library dependency),
  and `GET /features/<name>/<entity_id>`.
- Logging in `MaterializationJob.run()` (run summary at `INFO`, unknown-value
  entities at `WARNING`) and per-request logging in the HTTP layer, both through a
  plain `logging.getLogger(__name__)` that the package never configures itself.

CI/CD and dependency hygiene:

- GitHub Actions CI: lint (ruff), type-check (mypy), and tests (pytest, Python
  3.10 and 3.12) on every push and PR.
- Committed, pinned lockfiles (`requirements/*.txt`), a `lockfile-check` job that
  fails on drift from `pyproject.toml`, upper bounds on the `postgres`/`redis`
  extras, and a Dependabot config for weekly `pip` and `github-actions` updates.
- A `dependency-audit` job (`pip-audit` against every lockfile).
- A `build` job (sdist/wheel plus `twine check`) and a `publish` job that uploads
  to PyPI via Trusted Publishing (OIDC) when a `v*` tag is pushed. Pip caching on
  every job.
- A comment in `pyproject.toml` explaining why `dependencies = []` is
  correct-by-design: the core package only imports the standard library.
- A `docs` extra and an [mkdocs](https://www.mkdocs.org/) site (`docs/`), built
  with `mkdocs build --strict` on every push and deployed to GitHub Pages on
  pushes to `main`.

Security:

- Construction-time validation of `SqlEventSource`'s `table`, `entity_column`,
  `timestamp_column`, and `value_column`, closing a SQL-identifier injection point
  where those fields were interpolated directly into query text.

Testing:

- Property-based tests (Hypothesis) fuzzing `FeatureDefinition.reduce()`'s
  invariants and the offline/online no-skew guarantee across randomly generated
  event histories, aggregations, windows, and `as_of` values.

Docs and onboarding:

- `CONTRIBUTING.md`, `.env.example`, `Dockerfile`, and a devcontainer config.

### Fixed

- `cli.main()`'s `stdout` parameter was typed `io.TextIOBase`, which `sys.stdout`
  doesn't satisfy under mypy; retyped as `typing.TextIO`.
- `pyproject.toml`'s `license = { text = "MIT" }` (deprecated table form, warns on
  every build) switched to the SPDX string form `license = "MIT"`.
- The order-independence property test wrongly claimed `LATEST` is unaffected by
  input order. It isn't when two rows tie on the maximum timestamp (a stable sort
  keeps input order), so that case is now excluded from the property.

[Unreleased]: https://github.com/abdul-09/skew_balance_tool/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/abdul-09/skew_balance_tool/releases/tag/v0.1.0
