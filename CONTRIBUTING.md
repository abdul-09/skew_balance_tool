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
pip-compile --strip-extras --extra docs     -o requirements/docs.txt     pyproject.toml
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

### Docs

```bash
pip install -r requirements/docs.txt
mkdocs serve          # live-reloading preview at http://127.0.0.1:8000
mkdocs build --strict # what CI runs: fails on broken links and other warnings
```

`CONTRIBUTING.md` and `CHANGELOG.md` are served as pages of the site straight from
the repo root (see `docs_hooks/include_root_docs.py`), so there's one copy of each.

## What CI checks

Every push and PR runs, in `.github/workflows/ci.yml`:

- `lockfile-check` - the four `requirements/*.txt` files are recompiled
  fresh and diffed against what's committed; a stale lockfile fails the build
- `dependency-audit` - `pip-audit` against all four lockfiles
- `lint` - `ruff check skewproof tests`
- `typecheck` - `mypy skewproof`
- `test` - `pytest` on Python 3.10 and 3.12
- `docs` - `mkdocs build --strict`
- `build` - builds the sdist/wheel and validates packaging metadata

Two more jobs only run when they should: `pages` deploys the docs to GitHub Pages
on pushes to `main`, and `publish` uploads to PyPI when a `v*` tag is pushed (after
`build` and everything it depends on pass). Neither runs on pull requests.

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

## Releasing

A release is a `v*` tag. Pushing one runs the `publish` job, which uploads the
sdist and wheel that `build` produced to PyPI.

1. Move the `[Unreleased]` entries in `CHANGELOG.md` under a new version heading
   with the release date, and set `version` in `pyproject.toml` (and
   `__version__` in `skewproof/__init__.py`) to match.
2. Commit, and wait for CI to be green on `main`.
3. Tag and push:

   ```bash
   git tag -a v0.1.0 -m "skewproof 0.1.0"
   git push origin v0.1.0
   ```

One-time setup before the first release, none of which can be done from this repo:

- **PyPI Trusted Publishing.** The `publish` job authenticates with OIDC, not a
  stored token. On pypi.org, add a trusted publisher for `skewproof` with owner
  `abdul-09`, repository `skew_balance_tool`, workflow `ci.yml`, environment `pypi`.
  If the project doesn't exist on PyPI yet, register it as a *pending* publisher.
  Check the name `skewproof` is available first.
- **GitHub Pages.** In the repo's Settings -> Pages, set Source to "GitHub Actions"
  so the `pages` job has somewhere to deploy.

If you tag before the PyPI setup is done, `publish` fails at the upload step. The
tag itself is unaffected, and nothing is published.
