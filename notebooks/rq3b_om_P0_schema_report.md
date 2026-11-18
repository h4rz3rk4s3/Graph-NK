# RQ3b OpenMent — P0 schema audit

- Rules: version 0.2, 67 active, 9 candidate.
- Artefacts/units loaded: 75,284 threads, 1,335,605 TextUnits.
- Signals under the NK predicate: 737,508.
- Units with a known role: 566,369.

## Regression anchor (unfiltered pooled rates)

| role | units | tokens | nk | rate_per_1k |
| --- | --- | --- | --- | --- |
| mentee | 352631 | 9677476 | 161689 | 16.708 |
| mentor | 213738 | 5729562 | 137507 | 24.0 |

Expected target (pre-tuning rule set): mentor 51.837, mentee 39.471. The pattern YAMLs are being actively fine-tuned (2026-10, user decision), so the observed values may legitimately drift.

- mentor: observed 24.000 vs expected 51.837 → DRIFT
- mentee: observed 16.708 vs expected 39.471 → DRIFT

## Thread key

`thread_id` = `p.record_id` (`issue|pr:openment:<pid>:<n>`). `message_id` = thread + `:op` (title/body) or `:comment:<position>`.
OpenMent is GitHub-shaped: each issue/PR *is* the thread; no reply-graph reconstruction is needed. No Conversation node wraps OpenMent artefacts.

## Dates and provenance

Dates are anonymised day offsets (numeric), not ISO timestamps; the Word export shows relative elapsed days from the thread start.
Author = `u.author_login`; role from `project_roles.csv` (6,422 (project, user) mappings).

## HAS_TEXT roles

| tu_role | units |
| --- | --- |
| comment_body | 1189376 |
| title | 75280 |
| body | 70949 |

## Span-offset audit (random threads)

Offsets are character offsets into `TextUnit.text`. `char`/`char_loose` are exact matches; `search`/`failed` are the ones to watch.

| layer | char | char_unverified | total |
| --- | --- | --- | --- |
| classifier | 0 | 757 | 757 |
| lexical | 145 | 0 | 145 |
| morpho_syntactic | 1642 | 118 | 1760 |
| rhetorical | 14 | 0 | 14 |
| word_formation | 111 | 0 | 111 |
