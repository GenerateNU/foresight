# 0013. Only the request and the job runner commit

**Status:** Accepted · **Date:** 2026-10-15

## Context
When repositories or services commit on their own, a multi-step operation can
be left half-done, and tests can't roll their changes back.

## Decision
Exactly two places commit:
- **An HTTP request**: `database/session.get_session` commits once after the
  handler returns and rolls back on any error.
- **A background job**: `worker.run_job` commits after every chunk of work.

Repositories and services never commit. They flush when they need a generated
id, and use a savepoint when one statement may fail on its own (a rename that
hits a unique constraint).

## Consequences
- Every request is all-or-nothing.
- The session dependency runs with `scope="function"`, so the commit happens
  before the response is sent. A failed commit is a 500, never a false 200.
- See also [0036](0036-operator-commands-in-cli.md): an operator command is a
  third place that commits.
