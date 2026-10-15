# 0029. Every training run is a new, described version

**Status:** Accepted · **Date:** 2026-10-15

## Context
We want to improve the model and try new approaches, which means comparing
versions and remembering what each one tried.

## Decision
- Training is a job (`JobKind.TRAIN`). Every run saves a new version
  (decision [0009](0009-one-model-per-hotel.md)); none is overwritten.
- Each version stores a free-text `description` (what it tried) and a
  `training_summary` (window, nights used and excluded, room types, EBM
  settings, which signals had data), next to its `metrics`.
- `metrics` are scored on the newest 15% of nights, held out from fitting;
  they also calibrate the interval
  ([0005](0005-conformal-confidence-interval.md)).
- `activate: false` trains without serving, to compare first.
  `POST /models/{id}/activate` chooses which version serves.
- `copy_settings_from` retrains an earlier version's settings and window;
  anything sent explicitly overrides them.
- The EBM settings accepted are a fixed list (`interactions`,
  `learning_rate`, `max_bins`, `outer_bags`, `min_samples_leaf`,
  `smoothing_rounds`), validated in the request.

## Consequences
- Old versions keep their artifact, about 3 MB each on this hotel; prune
  them if storage matters.
- The fit runs in a thread, so the API keeps answering during training.
- One training job per hotel at a time (409 otherwise), which also avoids the
  version race noted in 0009.
