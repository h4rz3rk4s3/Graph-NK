"""
miner/gmane_ingester.py

Ingests the Webis Gmane Email Corpus (2019) into MongoDB `raw_emails` and
publishes pointer events to `stream_raw`, mirroring the GitHub miner's
contract: save to Mongo first, then publish a pointer event carrying the
real Mongo `_id` so downstream (extractor, projector Phase 0) can fetch the
full document.

Ingest scoping is therefore mandatory, not optional: use --groups (allowlist),
--lang, and --max. Filters are applied HERE so out-of-scope mail never enters
MongoDB.

NOTE ON ASSUMPTIONS (written without access to real corpus files; verify on
first contact with data — see CHANGELOG 2026-06-04 v0.6):
  A1. Records are strict line pairs (action line, then source line).
  A2. The action line carries the UUID under index._id, possibly wrapped in
      angle brackets ("<urn:uuid:...>"). We strip the brackets.
  A3. Header names arrive lowercased as documented (message_id, date, subject,
      from, to, cc, in_reply_to, references, list_id).
The parser tolerates violations of A1 (desynced pairs are re-synced by looking
for the next action line) and logs loudly on malformed records.

--- Ingestion throughput rework (see CHANGELOG) -----------------------------

The original implementation issued one MongoDB upsert and one Redis XADD per
email, each individually awaited — two to three serialized network round
trips per record, which is what capped throughput at ~300 items/s regardless
of how fast the parsing itself is. This version batches both:

  A4. (New, low-risk assumption used only for the optional group prefilter
      below): the corpus JSON is serialized such that any string value
      present in a document appears verbatim, quoted, somewhere in its raw
      line — true for any standard JSON encoder for plain-ASCII group names
      like "gmane.comp.python.devel", regardless of key name, casing, or
      nesting. Verify this holds if the prefilter's discard count looks
      implausibly low on first contact with real data.

Fixes applied:
  1. Batched Mongo writes: bulk_write() over 1,000s of docs instead of one
     upsert per record (storage.bulk_upsert_on_key).
  2. No read-back for the pointer event's mongo_id: pymongo generates and
     assigns `_id` client-side, purely locally, before any network call, on
     both the insert and (for genuinely new documents) the upsert path — see
     storage.bulk_upsert_on_key's docstring for the verified mechanism. A
     document that already existed from a prior run is correctly NOT
     re-published (its pointer event was already sent the first time it was
     ingested) — a deliberate correctness/efficiency improvement over the
     original code, which unconditionally republished on every re-run.
  3. Batched Redis publish: one pipelined XADD burst per flush
     (broker.publish_many) instead of one XADD per record.
  4. Cheap discard path: iter_bulk_records() can skip the expensive JSON
     parse entirely for source lines that provably cannot match the --groups
     allowlist (see A4), via a pure byte-substring check. This is a necessary-
     but-not-sufficient check — a match always falls through to the real
     parse + record_in_scope() confirmation, so it can never produce a false
     negative (never silently drops an in-scope record).
  5. Optional multi-process fan-out across input files (--parallel-files),
     since the corpus ships as many independent .gz files — embarrassingly
     parallel.
  6. Optional faster JSON (orjson) and gzip (python-isal) backends, used
     automatically if installed, with an unchanged stdlib fallback.
  7. --fresh-load: for a genuine first-time bulk import into an empty
     collection, uses plain inserts instead of upserts (avoids the internal
     query to check for an existing match that upsert performs even when
     keyed on an indexed field). The unique index on `urn` is still required
     to exist during the load either way, to reject duplicate urns (within a
     file or across files) — deferring that index does not combine safely
     with wanting duplicates rejected during the load itself, so it is NOT
     deferred; the throughput win in this mode comes purely from insert vs
     update semantics under an existing index, not from a deferred index.

Usage:
    # Incremental / idempotent (default) — safe to re-run over the same files
    python -m miner.gmane_ingester --files data/gmane/*.gz \
        --groups gmane.comp.python.devel gmane.comp.gcc.devel \
        --lang en --max 50000

    # First-time bulk import into an empty collection — fastest path
    python -m miner.gmane_ingester --files data/gmane/*.gz \
        --groups gmane.comp.python.devel --lang en --fresh-load

    # Fan out across files (embarrassingly parallel; corpus scale)
    python -m miner.gmane_ingester --files data/gmane/*.gz \
        --groups gmane.comp.python.devel --lang en \
        --fresh-load --parallel-files 8
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Iterator

from broker import get_broker
from progress import Progress
from settings import settings
from storage import bulk_upsert_on_key, make_mongo_client

logger = logging.getLogger("miner.gmane")

EMAIL_COLLECTION = "raw_emails"
PATH_TO_DATA = "/Volumes/Samsung SSD 990 PRO 4TB/Gmane_email_corpus/"

# Action lines ("{"index": {"_id": "..."}}") are always far shorter than this
# — a genuine email body/segment line is essentially never this short. Used
# to gate the group-prefilter fast path so it can never misclassify a real
# action line as a filterable source line (see A4 / fix #4 above).
_MIN_LEN_FOR_PREFILTER = 200


# ── Optional fast backends (auto-detected; stdlib fallback always works) ─────

try:
    import orjson

    def _parse_json(raw: str) -> Any:
        return orjson.loads(raw)

    _JSON_BACKEND = "orjson"
except ImportError:  # pragma: no cover - optional dependency
    def _parse_json(raw: str) -> Any:
        return json.loads(raw)

    _JSON_BACKEND = "stdlib json"

try:
    from isal import igzip as _gzip_module

    _GZIP_BACKEND = "python-isal"
except ImportError:  # pragma: no cover - optional dependency
    import gzip as _gzip_module

    _GZIP_BACKEND = "stdlib gzip"


# ── Record parsing ────────────────────────────────────────────────────────────

def _clean_urn(raw_id: str) -> str:
    """'<urn:uuid:c1d9...>' → 'urn:uuid:c1d9...'. Tolerates missing brackets."""
    return raw_id.strip().lstrip("<").rstrip(">")


def _group_prefilter_bytes(groups: list[str] | None) -> frozenset[bytes] | None:
    """
    Build the byte-string set used by iter_bulk_records' cheap discard path:
    each group name, quoted, as it would appear verbatim in a JSON-encoded
    line (see assumption A4 above). Returns None if no group filter is set.
    """
    if not groups:
        return None
    return frozenset(f'"{g}"'.encode("utf-8") for g in groups)


def iter_bulk_records(
    path: str,
    group_prefilter: frozenset[bytes] | None = None,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """
    Yield (urn, email_doc) pairs from one gzip file of ES bulk lines.

    Resilient to malformed lines: a JSON error or a desynced action/source pair
    logs a warning and re-syncs at the next action line instead of aborting the
    whole file. This resync behaviour is unchanged from the original parser
    when `group_prefilter` is None (the default) — existing tests exercising
    that path are unaffected.

    `group_prefilter`, if given, is a set of quoted group-name byte strings
    (from `_group_prefilter_bytes`) checked against a candidate source line
    BEFORE running the full JSON parse. This is a pure speed optimization:
    most of the corpus is typically out of scope at ingest time, and the JSON
    parse of a full email body is the expensive step, not a byte scan. The
    check is a *necessary* condition only — if none of the group strings
    appear anywhere in the raw line, the doc's `group` field cannot equal any
    of them, regardless of key name, casing, or nesting — so it can never
    produce a false negative. A match still falls through to the real parse +
    record_in_scope() check for confirmation. Only applied to lines at least
    `_MIN_LEN_FOR_PREFILTER` bytes long, since action lines are always far
    shorter — this guarantees the optimization can never misclassify a
    genuine action line as a discardable source line.
    """
    pending_urn: str | None = None
    with _gzip_module.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue

            if (
                group_prefilter is not None
                and pending_urn is not None
                and len(line) >= _MIN_LEN_FOR_PREFILTER
            ):
                line_bytes = line.encode("utf-8", errors="ignore")
                if not any(g in line_bytes for g in group_prefilter):
                    # Cannot possibly be in scope for any allowed group —
                    # skip the JSON parse of this (likely large) line entirely.
                    pending_urn = None
                    continue

            try:
                obj = _parse_json(line)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("%s:%d — malformed JSON, skipping line (%s)", path, line_no, exc)
                pending_urn = None
                continue

            if isinstance(obj, dict) and "index" in obj and isinstance(obj["index"], dict) and "_id" in obj["index"]:
                # Action line.
                if pending_urn is not None:
                    logger.warning("%s:%d — action line without source; resyncing", path, line_no)
                pending_urn = _clean_urn(str(obj["index"]["_id"]))
            else:
                # Source line.
                if pending_urn is None:
                    logger.warning("%s:%d — source line without action; skipping", path, line_no)
                    continue
                yield pending_urn, obj
                pending_urn = None


# ── Filtering ─────────────────────────────────────────────────────────────────

def record_in_scope(
    doc: dict[str, Any],
    groups: set[str] | None,
    langs: set[str] | None,
) -> bool:
    """Ingest-time scope: group allowlist and language filter. Authoritative —
    always re-checked here even when the group prefilter already passed a
    line through, since the prefilter is only a necessary, not sufficient,
    condition."""
    if groups is not None and doc.get("group") not in groups:
        return False
    if langs is not None and (doc.get("lang") or "") not in langs:
        return False
    return True


class _MaxReached(Exception):
    """Internal flow control for --max."""


# ── Ingest ────────────────────────────────────────────────────────────────────

async def ingest(
    file_paths: list[str],
    groups: list[str] | None = None,
    langs: list[str] | None = None,
    max_records: int | None = None,
    *,
    fresh_load: bool = False,
    batch_size: int | None = None,
) -> None:
    """
    Read corpus files, save in-scope emails to MongoDB, publish pointer
    events. Idempotent in the default mode: docs are upserted on urn;
    re-ingesting the same files is safe and cheap (already-present documents
    are matched, not re-inserted, and do not get a duplicate pointer event).

    Writes and publishes are batched (see module docstring, fixes #1-#3):
    accumulate up to `batch_size` records, then do one Mongo bulk_write and
    one pipelined Redis publish for the whole batch.
    """
    group_set = set(groups) if groups else None
    lang_set = set(langs) if langs else None
    group_prefilter = _group_prefilter_bytes(groups)
    batch_size = batch_size or settings.gmane_batch_size

    logger.info(
        "Backends: json=%s gzip=%s%s",
        _JSON_BACKEND, _GZIP_BACKEND,
        " fresh-load (insert-only)" if fresh_load else "",
    )

    mongo = make_mongo_client()
    db = mongo[settings.mongo_db_name]
    coll = db[EMAIL_COLLECTION]
    # Unique index on urn — required in BOTH modes: it's the upsert key in
    # the default mode, and it's what turns a duplicate urn into a rejected
    # write (instead of a silent extra document) in --fresh-load mode. This
    # call is idempotent/cheap if the index already exists.
    await coll.create_index("urn", unique=True)
    broker = await get_broker()

    prog = Progress("Ingest emails")
    ingested = scanned = published = 0
    pending_docs: list[dict[str, Any]] = []

    async def _flush() -> None:
        nonlocal published
        if not pending_docs:
            return
        new_docs = await bulk_upsert_on_key(
            coll, pending_docs, key_field="urn",
            use_insert_for_fresh_load=fresh_load,
        )
        if new_docs:
            events = [
                {
                    "item_type": "email",
                    "item_subtype": "email",
                    # repo_name carries the namespaced group so downstream
                    # plumbing (which keys on repo_name) works unchanged.
                    "repo_name": f"gmane:{d.get('group', '')}",
                    "mongo_id": str(d["_id"]),
                }
                for d in new_docs
            ]
            await broker.publish_many(settings.stream_raw, events)
            published += len(events)
        pending_docs.clear()

    try:
        for path in file_paths:
            logger.info("Reading %s", path)
            for urn, doc in iter_bulk_records(path, group_prefilter=group_prefilter):
                scanned += 1
                if not record_in_scope(doc, group_set, lang_set):
                    continue

                content_sha256 = hashlib.sha256(
                    json.dumps(doc, sort_keys=True, default=str).encode()
                ).hexdigest()

                pending_docs.append({
                    **doc,
                    "urn": urn,
                    "group": doc.get("group", ""),
                    "_meta": {
                        "item_type": "email",
                        "group": doc.get("group", ""),
                        "mined_at": datetime.now(timezone.utc).isoformat(),
                        "processed": False,
                        "content_sha256": content_sha256,
                    },
                })

                ingested += 1
                prog.add(1)
                prog.maybe_log()

                if len(pending_docs) >= batch_size:
                    await _flush()

                if max_records is not None and ingested >= max_records:
                    logger.info("Reached --max %d; stopping.", max_records)
                    raise _MaxReached
    except _MaxReached:
        pass
    finally:
        await _flush()
        prog.finish()
        mongo.close()
        logger.info(
            "Gmane ingest done: %d ingested / %d scanned (filters excluded %d) — "
            "%d new pointer events published (%d already present, skipped).",
            ingested, scanned, scanned - ingested,
            published, ingested - published,
        )


# ── Parallel fan-out across files ────────────────────────────────────────────

def _run_ingest_subset(args: tuple) -> None:
    """
    Entry point for one worker process: fresh interpreter (spawn start
    method), so logging must be configured again here. Runs `ingest()` to
    completion over its own subset of files with its own Mongo/Redis clients.
    """
    paths, groups, langs, max_records, fresh_load, batch_size = args
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    asyncio.run(
        ingest(paths, groups, langs, max_records, fresh_load=fresh_load, batch_size=batch_size)
    )


def ingest_parallel(
    file_paths: list[str],
    groups: list[str] | None,
    langs: list[str] | None,
    max_records: int | None,
    num_workers: int,
    *,
    fresh_load: bool = False,
    batch_size: int | None = None,
) -> None:
    """
    Split file_paths round-robin across `num_workers` processes, each running
    its own `ingest()` to completion. The corpus ships as many independent
    .gz files, so this is embarrassingly parallel — no coordination needed
    between workers beyond MongoDB's own concurrent-write handling.

    If `max_records` is set, it is divided (ceiling) across workers as a
    per-worker cap, so the total ingested is an approximate, not exact, global
    cap — acceptable for research-scale runs; use a single process (the
    default when --parallel-files is not given) if an exact --max is required.
    """
    from concurrent.futures import ProcessPoolExecutor

    buckets: list[list[str]] = [file_paths[i::num_workers] for i in range(num_workers)]
    buckets = [b for b in buckets if b]  # drop empty buckets if fewer files than workers
    per_worker_max = None
    if max_records is not None:
        per_worker_max = -(-max_records // len(buckets))  # ceiling division
        logger.info(
            "--max %d split across %d worker(s) as an approximate per-worker cap of %d each.",
            max_records, len(buckets), per_worker_max,
        )

    logger.info("Fanning out %d file(s) across %d worker process(es).", len(file_paths), len(buckets))
    with ProcessPoolExecutor(max_workers=len(buckets)) as pool:
        args_list = [
            (bucket, groups, langs, per_worker_max, fresh_load, batch_size)
            for bucket in buckets
        ]
        list(pool.map(_run_ingest_subset, args_list))
    logger.info("All %d worker process(es) finished.", len(buckets))


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    p = argparse.ArgumentParser(description="Ingest Webis Gmane Email Corpus files.")
    p.add_argument("--files", nargs="+", required=True,
                   help="Corpus .gz files (globs ok).")
    p.add_argument("--groups", nargs="*", default=None,
                   help="Gmane group allowlist (default: all — NOT recommended at corpus scale).")
    p.add_argument("--lang", nargs="*", default=["en"],
                   help="Language filter (default: en). Pass no value to disable.")
    p.add_argument("--max", type=int, default=None,
                   help="Stop after this many ingested emails.")
    p.add_argument("--fresh-load", action="store_true",
                   help="First-time bulk import into an empty collection: uses plain "
                        "inserts instead of upserts (fastest path). Do not use if "
                        "raw_emails already has data you want update-on-conflict "
                        "semantics for.")
    p.add_argument("--batch-size", type=int, default=None,
                   help=f"Records per Mongo bulk_write / Redis publish flush "
                        f"(default: settings.gmane_batch_size = {settings.gmane_batch_size}).")
    p.add_argument("--parallel-files", type=int, default=1,
                   help="Number of worker processes to fan out across input files "
                        "(1 = single process, default). Only helps with >1 input file.")
    args = p.parse_args()

    paths: list[str] = []
    for pattern in args.files:
        paths.extend(sorted(glob.glob(PATH_TO_DATA + pattern)))
    if not paths:
        raise SystemExit("No files matched --files.")

    if not args.groups and args.max is None:
        logger.warning(
            "No --groups and no --max: you are about to ingest EVERYTHING in the "
            "given files. At full-corpus scale (153M emails) this is almost "
            "certainly not what you want."
        )

    if args.parallel_files > 1 and len(paths) > 1:
        ingest_parallel(
            paths, args.groups, args.lang or None, args.max,
            num_workers=min(args.parallel_files, len(paths)),
            fresh_load=args.fresh_load, batch_size=args.batch_size,
        )
    else:
        asyncio.run(
            ingest(
                paths, args.groups, args.lang or None, args.max,
                fresh_load=args.fresh_load, batch_size=args.batch_size,
            )
        )


if __name__ == "__main__":
    main()
