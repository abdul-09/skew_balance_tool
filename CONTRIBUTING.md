# Contributing

## Setup

```bash
pip install -e ".[dev]"
```

`requirements/dev.txt` is a pinned, committed lockfile compiled from
`pyproject.toml`'s `dev` extra with `pip-compile` (from `pip-tools`). If you
want the exact versions CI uses instead of whatever resolves today:

```bash
pip install -r requirements/dev.txt
pip install -e . --no-deps
```

If you're touching `postgres = [...]` or `redis = [...]` in
`pyproject.toml`, regenerate the matching lockfile so `lockfile-check` (see
below) doesn't fail your PR:

```bash
pip install pip-tools
pip-compile --strip-extras --extra dev     -o requirements/dev.txt      pyproject.toml
pip-compile --strip-extras --extra postgres -o requirements/postgres.txt pyproject.toml
pip-compile --strip-extras --extra redis    -o requirements/redis.txt    pyproject.toml
```

## Running things locally

```bash
pytest                        # tests, 100% line+branch coverage required
ruff check skewproof tests    # lint
mypy skewproof                # type-check
python -m skewproof.cli demo  # the end-to-end demo from the README
```

### Integration tests (optional)

The Postgres and Redis tests are skipped unless their env var is set. Bring
up real services and point the tests at them:

```bash
docker compose -f deploy/docker-compose.yml up -d
pip install -e ".[dev,postgres,redis]"
cp .env.example .env   # then edit if your setup differs from the defaults
set -a && source .env && set +a
pytest
```

## What CI checks

Every push and PR runs, in `.github/workflows/ci.yml`:

- `lockfile-check` - the three `requirements/*.txt` files are recompiled
  fresh and diffed against what's committed; a stale lockfile fails the build
- `dependency-audit` - `pip-audit` against all three lockfiles
- `lint` - `ruff check skewproof tests`
- `typecheck` - `mypy skewproof`
- `test` - `pytest` on Python 3.10 and 3.12
- `build` - builds the sdist/wheel and validates packaging metadata

A merge to `main` doesn't publish anything. Publishing to PyPI only happens
when a `v*` tag is pushed, and only after all of the above pass.

## Style

- Ruff is configured for `E`, `F`, `I` (pycodestyle errors, pyflakes, import
  sorting) at a 100-char line length - see `[tool.ruff]` in `pyproject.toml`.
  It's deliberately not configured with a broader rule set (e.g. enforcing
  timezone-aware datetimes); keep new code consistent with what's already
  here rather than "fixing" pre-existing patterns as a drive-by.
- Full type hints are expected; `mypy skewproof` must pass with no errors.
- Every dataclass field that ends up interpolated into a string that isn't a
  bind parameter (SQL, shell, etc.) needs `__post_init__` validation - see
  `SqlEventSource` for the pattern.
- Coverage is enforced at 100% (line and branch) via `--cov-fail-under=100`
  in `pyproject.toml`. New code needs tests, not a coverage exemption.

## Commit messages

This repo uses `area: short description` (e.g. `materialize: add logging to
the batch materialization loop`), matching `git log --oneline`.
