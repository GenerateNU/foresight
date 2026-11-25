# Archive

Research kept for reference. Nothing here is part of the app, is linted, or is
kept up to date.

## experiments/

The feature screening behind #139 and decisions
[0051](../../docs/decisions/0051-calendar-only-model.md),
[0055](../../docs/decisions/0055-events-back-in-the-model.md) and
[0067](../../docs/decisions/0067-night-before-holiday-input.md): a LASSO screen
of candidate inputs, EBM tests of the survivors, baselines, COVID recovery, and
the feature inventory.

They use the app's code as of the clean-up (#155), so they may break as it
changes. `candidates.py`, and `lasso_screen.py` which imports it, already
don't run: `booking_curves` was removed in 0082. The plotting scripts need
`matplotlib`, which isn't a dependency; `uv run --with matplotlib` adds it.
