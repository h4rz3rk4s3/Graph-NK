"""
Gmane Ingester — reads the Webis Gmane Email Corpus 2019 into the pipeline.

Corpus format (per Webis documentation): Gzip-compressed files of line-based
JSON in Elasticsearch bulk format. Each record is a PAIR of lines:

    {"index": {"_id": "<urn:uuid:...>"}}
    {"headers": {...}, "text_plain": "...", "lang": "en",
     "segments": [{"begin": 0, "end": 99, "label": "paragraph"}, ...],
     "group": "gmane.comp.python.devel"}

This ingester is the email counterpart of miner/async_miner.py and honours the
exact same contract: persist the raw document to MongoDB FIRST, then publish a
lightweight pointer event to stream_raw. Everything downstream (extractor,
annotators, projector) then works unchanged.

SCALE WARNING — the full corpus is 153M emails across 14,699 lists: four orders
of magnitude beyond the GitHub pilot. Ingest scoping is therefore mandatory,
not optional: use --groups (allowlist), --lang, and --max. Filters are applied
HERE so out-of-scope mail never enters MongoDB.

NOTE ON ASSUMPTIONS (written without access to real corpus files; verify on
first contact with data — see CHANGELOG 2026-06-04 v0.6):
  A1. Records are strict line pairs (action line, then source line).
  A2. The action line carries the UUID under index._id, possibly wrapped in
      angle brackets ("<urn:uuid:...>"). We strip the brackets.
  A3. Header names arrive lowercased as documented (message_id, date, subject,
      from, to, cc, in_reply_to, references, list_id).
The parser tolerates violations of A1 (desynced pairs are re-synced by looking
for the next action line) and logs loudly on malformed records.

Usage:
    python -m miner.gmane_ingester --files data/gmane/*.gz \
        --groups gmane.comp.python.devel gmane.comp.gcc.devel \
        --lang en --max 50000
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import gzip
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Iterator

from progress import Progress
from settings import settings

# NOTE: broker/storage (redis, motor) are imported lazily inside ingest() so the
# pure parsing/filtering functions in this module stay importable and testable
# without any services installed.

logger = logging.getLogger("miner.gmane")

EMAIL_COLLECTION = "raw_emails"
PATH_TO_DATA = "/Volumes/Samsung SSD 990 PRO 4TB/Gmane_email_corpus/"

# ── Record parsing ────────────────────────────────────────────────────────────

def _clean_urn(raw_id: str) -> str:
    """'<urn:uuid:c1d9...>' → 'urn:uuid:c1d9...'. Tolerates missing brackets."""
    return raw_id.strip().lstrip("<").rstrip(">")


def iter_bulk_records(path: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """
    Yield (urn, email_doc) pairs from one gzip file of ES bulk lines.

    Resilient to malformed lines: a JSON error or a desynced action/source pair
    logs a warning and re-syncs at the next action line instead of aborting the
    whole file.
    """
    pending_urn: str | None = None
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("%s:%d — malformed JSON, skipping line (%s)", path, line_no, exc)
                pending_urn = None
                continue

            if "index" in obj and isinstance(obj["index"], dict) and "_id" in obj["index"]:
                # Action line
                if pending_urn is not None:
                    logger.warning("%s:%d — action line without source; resyncing", path, line_no)
                pending_urn = _clean_urn(str(obj["index"]["_id"]))
            else:
                # Source line
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
    """Ingest-time scope: group allowlist and language filter."""
    if groups is not None and doc.get("group") not in groups:
        return False
    if langs is not None and (doc.get("lang") or "") not in langs:
        return False
    return True


# ── Ingest ────────────────────────────────────────────────────────────────────

async def ingest(
    file_paths: list[str],
    groups: list[str] | None = None,
    langs: list[str] | None = None,
    max_records: int | None = None,
) -> None:
    """
    Read corpus files, save in-scope emails to MongoDB, publish pointer events.
    Idempotent: docs are upserted on urn; re-ingesting the same files is safe.
    """
    group_set = set(groups) if groups else None
    lang_set = set(langs) if langs else None

    from broker import get_broker
    from storage import make_mongo_client

    mongo = make_mongo_client()
    db = mongo[settings.mongo_db_name]
    coll = db[EMAIL_COLLECTION]
    await coll.create_index("urn", unique=True)
    broker = await get_broker()

    prog = Progress("Ingest emails")
    ingested = scanned = 0

    try:
        for path in file_paths:
            logger.info("Reading %s", path)
            for urn, doc in iter_bulk_records(path):
                scanned += 1
                if not record_in_scope(doc, group_set, lang_set):
                    continue

                headers = doc.get("headers") or {}
                content_sha256 = hashlib.sha256(
                    json.dumps(doc, sort_keys=True, default=str).encode()
                ).hexdigest()

                res = await coll.update_one(
                    {"urn": urn},
                    {"$set": {
                        **doc,
                        "urn": urn,
                        "_meta": {
                            "item_type": "email",
                            "group": doc.get("group", ""),
                            "mined_at": datetime.now(timezone.utc).isoformat(),
                            "processed": False,
                            "content_sha256": content_sha256,
                        },
                    }},
                    upsert=True,
                )
                if res.upserted_id is not None:
                    mongo_id = res.upserted_id
                else:
                    found = await coll.find_one({"urn": urn}, {"_id": 1})
                    mongo_id = found["_id"]

                await broker.publish(settings.stream_raw, {
                    "item_type":    "email",
                    "item_subtype": "email",
                    # repo_name carries the namespaced group so downstream
                    # plumbing (which keys on repo_name) works unchanged.
                    "repo_name":    f"gmane:{doc.get('group', '')}",
                    "mongo_id":     str(mongo_id),
                })

                ingested += 1
                prog.add(1)
                prog.maybe_log()
                if max_records is not None and ingested >= max_records:
                    logger.info("Reached --max %d; stopping.", max_records)
                    raise _MaxReached
    except _MaxReached:
        pass
    finally:
        prog.finish()
        mongo.close()
        logger.info(
            "Gmane ingest done: %d ingested / %d scanned (filters excluded %d).",
            ingested, scanned, scanned - ingested,
        )


class _MaxReached(Exception):
    """Internal flow control for --max."""


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

    asyncio.run(ingest(paths, args.groups, args.lang or None, args.max))


if __name__ == "__main__":
    main()

# python -m miner.gmane_ingester --files webis-gmane-19-part01.gz --max 50000