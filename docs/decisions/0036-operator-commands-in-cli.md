# 0036. Operator commands live in `cli.py` and commit once

**Status:** Accepted · **Date:** 2026-10-25

## Context
Linking a user to a hotel has no place in the app yet, so it is done from the
command line. [0013](0013-one-transaction-per-unit-of-work.md) says exactly two
places commit, the request and the job runner, and a command-line process is
neither.

## Decision
- Operator commands live in `foresight/cli.py` and run as
  `python -m foresight.cli <command>`. Each has a `just` recipe that takes
  `--neon` like the others (`just link-user <email> <hotel_id>`).
- A command is a third place that commits, alongside the two in 0013. It opens
  a session from `async_session_factory` and commits once, when the whole
  command has succeeded. A `DomainError` is printed, the command exits 1, and
  nothing is committed.
- It reaches data only through services ([0012](0012-layered-architecture.md)).
  `cli.py` holds no queries and no business rules.
- A command is for something the app can't do yet, and goes when the app can.

## Consequences
- A command is all-or-nothing, like a request.
- A new command is a subparser and a function in `cli.py`, plus a recipe.
