"""
OCEAN Ingester — reads the OCEAN mailing-list JSONL datasets into the pipeline.

Corpus format: plain-text (NOT gzip, NOT ES-bulk) JSONL — one self-contained
JSON object per line. Each record is a flat dictionary (verified in
email_eda.ipynb):

    {old_index, from_name, from_email, raw_from_string, to_name, to_email,
     raw_to_string, cc_name, cc_email, raw_cc_string, subject, date (epoch ms),
     raw_date_string, message_id, in_reply_to, refs (list), raw_refs_string,
     body_text, body_html, body_image, content_type, log, flagged_abuse,
     original_url, mailing_list, filename, time_stamp, week, month, day, year}

UNLIKE Webis Gmane (miner/gmane_ingester.py) the OCEAN records carry no
precomputed `segments`, `headers`, `lang`, or `group`. This ingester therefore:
  1. derives a namespaced, collision-safe `urn` = "ocean:<mailing_list>:<message_id>";
  2. builds a minimal `headers` dict (from/to/cc/subject/date/message_id/
     in_reply_to/references) so the projector's email path
     (graph_projector.upsert_email_message) works unchanged;
  3. hardcodes `lang = "en"` (OCEAN lists are English — documented assumption);
  4. maps `group` = `mailing_list` for the MailingList layer;
  5. persists the doc to MongoDB `raw_emails` FIRST, then publishes a pointer
     event to stream_raw with repo_name = "ocean:<mailing_list>" so the
     extractor worker routes it to extract_from_ocean_email
     (extractor/text_unit_extractor.py, dispatch in extractor/worker.py).

EXTENSION override: rather than reusing extract_from_email (which needs segment
spans), OCEAN mail is extracted at message granularity by the dedicated
extract_from_ocean_email — see CHANGELOG 2026-08-10. The projector's EmailMessage
wiring is corpus-agnostic, so no projector change is required.

Usage:
    python -m miner.ocean_ingester --files ocean_dataset/python_clean.jsonl --lists python --max 5000
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import hashlib
import json
import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

from progress import Progress
from settings import settings

# broker/storage (redis, motor) are imported lazily inside ingest() so the pure
# parsing/filtering functions stay importable and testable without services.

logger = logging.getLogger("miner.ocean")

EMAIL_COLLECTION = "raw_emails"  # shared with miner/gmane_ingester.py
DEFAULT_LIST_DIR = "ocean_dataset/"


# ── Record parsing ────────────────────────────────────────────────────────────


def iter_ocean_records(
    path: str,
    *,
    progress_cb: Callable[[int], None] | None = None,
    progress_every_lines: int = 2000,
) -> Iterator[dict[str, Any]]:
    """
    Yield one flat doc per line from a plain-text OCEAN JSONL file.

    Resilient to malformed lines: a JSON error or blank line logs a warning
    and continues instead of aborting the file.

    progress_cb (optional, default off): called every `progress_every_lines`
    records with the byte offset consumed from the file (monotonic, bounded by
    os.path.getsize(path)) — the only cheap way to estimate ETA without knowing
    the record count in advance.
    """
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, start=1):
            if (
                progress_cb is not None
                and progress_every_lines
                and line_no % progress_every_lines == 0
            ):
                progress_cb(fh.tell())
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("%s:%d — malformed JSON, skipping line (%s)", path, line_no, exc)


# ── Renormalisation ───────────────────────────────────────────────────────────


def derive_urn(flat: dict[str, Any]) -> str:
    """
    Namespaced, collision-safe unique id for a flat OCEAN record.

    "ocean:<mailing_list>:<message_id>" — the prefix mirrors the repo_name
    namespace and the message_id disambiguates within a list. A bare
    message_id could collide across lists and silently clobber an upsert.
    """
    mailing_list = flat.get("mailing_list") or "unknown"
    message_id = (
        flat.get("message_id")
        or hashlib.sha1(json.dumps(flat, sort_keys=True, default=str).encode()).hexdigest()
    )
    return f"ocean:{mailing_list}:{message_id}"


def build_headers(flat: dict[str, Any]) -> dict[str, Any]:
    """
    Map the flat OCEAN fields onto the gmane-shaped `headers` dict the
    projector's email path expects (graph_projector.upsert_email_message).

    from → raw_from_string (or from_email); date → raw_date_string (kept as
    the human string, matches how extract uses created_at); references →
    refs (a list of message ids). Fields absent in the flat record are omitted.
    """
    headers: dict[str, Any] = {}
    for src, dst in [
        ("message_id", "message_id"),
        ("subject", "subject"),
        ("in_reply_to", "in_reply_to"),
    ]:
        if flat.get(src) is not None:
            headers[dst] = flat[src]
    if flat.get("raw_date_string") is not None:
        headers["date"] = flat["raw_date_string"]
    from_val = flat.get("raw_from_string") or flat.get("from_email")
    if from_val is not None:
        headers["from"] = from_val
    to_val = flat.get("raw_to_string") or flat.get("to_email")
    if to_val is not None:
        headers["to"] = to_val
    if flat.get("cc_name") is not None or flat.get("raw_cc_string") is not None:
        headers["cc"] = flat.get("raw_cc_string") or flat.get("cc_name")
    if flat.get("refs"):
        headers["references"] = list(flat["refs"])
    return headers


def to_email_doc(flat: dict[str, Any]) -> dict[str, Any]:
    """
    Wrap a flat OCEAN record as a gmane-shaped email doc for Mongo + projector.

    Preserves every source field verbatim, then adds the derived urn, headers,
    group (mailing_list), lang ("en"), and _meta. The new extractor
    (extract_from_ocean_email) reads subject/body_text/raw_from_string/
    raw_date_string directly from the flat fields; the projector reads the
    derived headers/group/urn/lang.
    """
    urn = derive_urn(flat)
    return {
        **flat,
        "urn": urn,
        "headers": build_headers(flat),
        "group": flat.get("mailing_list") or "",
        "lang": "en",
        "_meta": {
            "item_type": "email",
            "group": flat.get("mailing_list", ""),
            "mined_at": datetime.now(UTC).isoformat(),
            "processed": False,
            "content_sha256": hashlib.sha256(
                json.dumps(flat, sort_keys=True, default=str).encode()
            ).hexdigest(),
        },
    }


# ── Ingest-time scope ─────────────────────────────────────────────────────────


def record_in_scope(flat: dict[str, Any], lists: set[str] | None) -> bool:
    """Ingest-time scope: mailing-list allowlist (None = all)."""
    if lists is not None and flat.get("mailing_list") not in lists:
        return False
    return True


# ── Ingest ────────────────────────────────────────────────────────────────────


async def ingest(
    file_paths: list[str],
    lists: list[str] | None = None,
    max_records: int | None = None,
) -> None:
    """
    Read OCEAN JSONL files, save in-scope emails to MongoDB, publish pointers.
    Idempotent: docs are upserted on urn; re-ingesting is safe.
    """
    list_set = set(lists) if lists else None

    from broker import get_broker
    from storage import make_mongo_client

    mongo = make_mongo_client()
    db = mongo[settings.mongo_db_name]
    coll = db[EMAIL_COLLECTION]
    await coll.create_index("urn", unique=True)
    broker = await get_broker()

    prog = Progress("Ingest OCEAN emails")
    ingested = scanned = 0

    try:
        for path in file_paths:
            logger.info("Reading %s", path)
            for flat in iter_ocean_records(path):
                scanned += 1
                if not record_in_scope(flat, list_set):
                    continue

                doc = to_email_doc(flat)

                res = await coll.update_one(
                    {"urn": doc["urn"]},
                    {"$set": doc},
                    upsert=True,
                )
                if res.upserted_id is not None:
                    mongo_id = res.upserted_id
                else:
                    found = await coll.find_one({"urn": doc["urn"]}, {"_id": 1})
                    mongo_id = found["_id"]

                await broker.publish(
                    settings.stream_raw,
                    {
                        "item_type": "email",
                        "item_subtype": "email",
                        # repo_name carries the namespaced list so the extractor
                        # worker routes to extract_from_ocean_email and downstream
                        # plumbing (which keys on repo_name) works unchanged.
                        "repo_name": f"ocean:{doc.get('group', '')}",
                        "mongo_id": str(mongo_id),
                    },
                )

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
            "OCEAN ingest done: %d ingested / %d scanned (filters excluded %d).",
            ingested,
            scanned,
            scanned - ingested,
        )


class _MaxReached(Exception):
    """Internal flow control for --max."""


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    p = argparse.ArgumentParser(description="Ingest OCEAN mailing-list JSONL files.")
    p.add_argument("--files", nargs="+", required=True, help="OCEAN .jsonl files (globs ok).")
    p.add_argument(
        "--lists", nargs="*", default=None, help="mailing-list allowlist (default: all)."
    )
    p.add_argument("--max", type=int, default=None, help="Stop after this many ingested emails.")
    args = p.parse_args()

    paths: list[str] = []
    for pattern in args.files:
        paths.extend(sorted(glob.glob(pattern)))
    if not paths:
        raise SystemExit(
            "No files matched --files. "
            "Note: python_clean.jsonl is ~2.6GB — prefer --max for a quick test."
        )

    asyncio.run(ingest(paths, args.lists, args.max))


if __name__ == "__main__":
    main()
