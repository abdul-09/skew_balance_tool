# Testing the core guarantee

`tests/test_definition.py` and `tests/test_online.py` check `reduce()` and the
no-skew claim against handwritten examples. Two more files fuzz the same things
with [Hypothesis](https://hypothesis.readthedocs.io/), generating hundreds of
random cases per run instead of a handful of fixtures:

- `tests/test_definition_properties.py` - invariants `reduce()` must satisfy for
  *any* input: no row after `as_of` can affect the result, row order doesn't
  matter (except for the one genuinely order-dependent case, below), `SUM == MEAN * COUNT`,
  `MIN <= MEAN <= MAX`, and the window boundary is inclusive (checked both against
  an independently-written reference filter and with an explicit exact-boundary
  case, since random timestamps almost never land precisely on a boundary).
- `tests/test_no_skew_properties.py` - the offline training value and the
  online served value agree for randomly generated event histories, `as_of`
  values, aggregations, and windows, against every in-process store.

A few things worth knowing about how these were validated:

- They were checked against deliberately reintroduced bugs (a `<=`/`<`
  inclusive-boundary slip, and a one-second skew between the offline and online
  value) to confirm they actually fail on a broken implementation.
- Two of the first drafts missed those bugs because random timestamps almost
  never land exactly on a boundary or within a second of a real event. That's why
  there's a dedicated exact-boundary test, and why the no-skew test anchors
  `as_of` near real event timestamps part of the time.
- **`LATEST` is not order-independent when two rows tie on the maximum
  timestamp.** `reduce()` uses a stable sort, so which tied row wins depends on
  input order. That's defined behavior, so the order-independence property
  excludes exactly that case rather than asserting something false about it.

## What CI checks

Every push and PR runs `lockfile-check`, `dependency-audit`, `lint` (ruff),
`typecheck` (mypy), `test` (pytest on Python 3.10 and 3.12, 100% line and
branch coverage required), `docs` (`mkdocs build --strict`), and `build`
(sdist/wheel + `twine check`). See [CONTRIBUTING.md](contributing.md) for
running these locally.
