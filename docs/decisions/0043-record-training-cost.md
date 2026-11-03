# 0043. Every version records how long its fit took and how much memory it used

**Status:** Accepted · **Date:** 2026-11-02

## Context
Before recommending how often to retrain, we need to know what a training run
costs. The train job already reported the run's total seconds in its
progress, but nothing was saved on the version, and memory wasn't measured at
all. Since [0042](0042-refit-on-every-row.md) every run fits twice, so the
cost roughly doubled.

## Decision
- `ml/resources.measure` wraps the `EBMModel.fit` call in
  `pricing_model._fit` (both fits, not data loading). It adds three numbers to
  the version's `metrics`:
  - `train_seconds`: wall-clock time of the fit.
  - `peak_memory_mb`: the highest resident memory seen during the fit.
  - `added_memory_mb`: that peak minus the memory before the fit, which is
    what the fit itself cost.
- They go in the existing `metrics` JSONB, so no migration is needed and they
  show up in the model listing. The train job's progress shows
  `train_seconds` and `peak_memory_mb` next to the scores.
- Memory is measured with `psutil`, counting this process **and its children**:
  - EBM fits in parallel with joblib worker processes (`n_jobs=-2`), so most
    of its memory is outside the API process.
  - The API is a long-lived process, so `resource.ru_maxrss` (the peak since
    start) would stick at the largest run ever.
  - Memory is sampled every 0.1 s on a background thread.

## Consequences
- A new dependency, `psutil`. The Docker image needs rebuilding.
- A spike shorter than 0.1 s can be missed; fits take seconds, so the peak is
  close but not exact.
- `added_memory_mb` can understate a fit's cost if the process already holds
  freed memory that the fit reuses. Compare it across versions trained under
  similar conditions.
- Joblib can keep worker processes alive between fits, so their memory may
  already count toward the baseline on a later run.
- Versions trained before this decision don't have these keys.
- `TrainingResult.seconds` in the job progress still times the whole run,
  data loading included.
