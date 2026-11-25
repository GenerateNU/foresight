# 0088. One docstring and comment style

**Status:** Accepted · **Date:** 2026-11-24 · Amends [0030](0030-schema-descriptions-and-examples.md)

## Context
The backend used three docstring styles, two kinds of section marker, inline
comments that explained what code did, and comments that cited decision numbers
instead of saying the reason. Module docstrings repeated what the file name and
the function docstrings already said. `ml/ebm.py` had untyped methods.

## Decision
- Every function, private ones included, has a Google docstring: a one-line
  summary, then `Args:`, `Returns:` or `Yields:`, and `Raises:` where they
  apply. Every class that isn't a schema or an enum lists its fields under
  `Attributes:`.
- No module docstrings. What a module is for goes in the docstrings of its
  main functions.
- Box banners (`╭─╮ │ Name │ ╰─╯`) are the only section marker.
- Inline comments only when the code can't say it, and never a decision
  number: write the reason instead.
- Everything is typed. No `from __future__ import annotations`.
- ruff enforces docstrings (`D`, Google convention) and annotations (`ANN`).
- In `routes/`, two exceptions keep `/docs` clean:
  - An endpoint's docstring puts `Args:`/`Returns:`/`Raises:` after a form
    feed (`\f`). FastAPI shows only the text before it. ruff's `D301` is
    turned off for `routes/` for this.
  - A request or response schema has a one-line docstring and no
    `Attributes:`. Each field's `Field(description=...)` documents it, and
    the docstring becomes the schema's description in `/docs`.

## Consequences
- Reading any function tells you what it takes, returns and raises, without
  opening its callers.
- Reasons live next to the code, so a comment stays true even if a decision
  record is renumbered or superseded.
- Docstrings are longer; the summary line stays short.
