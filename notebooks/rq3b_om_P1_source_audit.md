# RQ3b OpenMent — P1 hygiene note

## Source-file artifact (`comments.csv`)

- rows: 1,218,538; distinct `comment_id`: 858,747; **extra duplicate rows: 359,791 (29.5%)**.
- comment ids appearing on >1 row: 189,637.
- rows carrying a second (`_y`) comment: 346,630.

The ingester reads only the `_x` columns and emits every CSV row as a TextUnit, so each duplicate row becomes a duplicated comment unit with identical text but a different `creation_day_x`. This is the artifact behind the `is_repeat` rate, not (mostly) genuine repetition.

## Rate by filter

| filter | mentee | mentor | gap_rel_pct |
| --- | --- | --- | --- |
| no_boilerplate | 16.569 | 24.099 | 45.445 |
| no_nonprose | 16.736 | 24.313 | 45.269 |
| no_quote_markers | 16.797 | 24.044 | 43.141 |
| no_quoted | 16.509 | 24.092 | 45.937 |
| no_repeats | 16.411 | 24.052 | 46.559 |
| no_signature | 16.578 | 24.128 | 45.54 |
| none | 16.708 | 24.0 | 43.643 |

Removing repeats and other hygiene flags does **not** close the mentor−mentee gap (it slightly widens it), so the artifact is not the source of the role asymmetry. See the plan's P2–P5 for the substantive decomposition.
