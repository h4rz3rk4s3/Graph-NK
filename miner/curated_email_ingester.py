"""
Curated Email Code Reviews Ingester (v0.8).

The curated email code-review datasets from:
  Liang, J., et al.; "curated email-based code reviews" (the local PDF is
  Liang2024_curatedEmailCodeReview.pdf), derived from Patchwork archives.
Local dataset:
  /Volumes/Samsung SSD 990 PRO 4TB/Graph_NK_datasets/
    Curated Email-Based Code Reviews Datasets/{ffmpeg,kernel,ozlabs}/

Per project there are Patchwork entity `.jl` files (one JSON object per line).
We ingest the text-bearing entities as `EmailMessage`s, OCEAN-style (flat doc,
message granularity — no segment spans):

  - *mailinglist.jl  → email subject + content
  - *comment.jl      → review comment subject + msg_content (in_reply_to)
  - *patch.jl        → patch cover/annotated message (msg_content); code_diff
                       is code, NOT authored NL discourse, so it is excluded
                       (same rationale as the Gmane quotation exclusion)
  - *series.jl       → series cover_letter_content

Patch/change/identity/individual/project entity links are NOT ingested — the
material identities and patch groupings are inferred by the paper and are kept
out of the NK corpus (provenance only, stored as refs in metadata).

The docs are written to raw_emails and routed to extract_from_ocean_email by
the "curatedemail:" repo namespace (see extractor.text_unit_extractor).

Usage:
    python -m miner.curated_email_ingester [--path <root>]
        [--projects ffmpeg kernel ozlabs] [--max N] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import logging
import os
from collections.abc import Iterator
from typing import Any

from miner.external_common import (
    content_sha256,
    external_event,
    run_external_ingest,
)
from settings import settings

logger = logging.getLogger("miner.curated_email")

CORPUS_ID = "curated-email-code-reviews"
PLATFORM_ID = "mailing_list"
EMAIL_COLLECTION = "raw_emails"

# Default sampling rates targeting ~5,000,000 records total (100% of smallest project
# ffmpeg, and ~44.84% proportional entity sample from ozlabs and kernel).
DEFAULT_SAMPLE_RATES: dict[str, float] = {
    "ffmpeg": 1.0,
    "ozlabs": 0.4484,
    "kernel": 0.4484,
}

# Entity files we turn into emails; the rest (change1/2, identity, individual,
# project, newseries) are structural references we deliberately skip.
EMAIL_ENTITY_SUFFIXES = ("mailinglist.jl", "comment.jl", "patch.jl", "series.jl")

# Records whose body exceeds this many whitespace tokens are dropped at ingest.
# Review comments occasionally embed the FULL quoted patch incl. git binary
# blobs (e.g. kernel-comment-24774599), pushing the raw Mongo doc past the
# 16 MiB BSON limit and failing the whole 2000-doc bulk batch. Authored
# epistemic discourse never approaches this length; oversized bodies are
# auto-generated/patch-embedded content (CHANGELOG 2026-08-18).
DEFAULT_MAX_WORDS: int = 20000


def iter_email_files(root: str, projects: list[str]) -> list[str]:
    files: list[str] = []
    for project in projects:
        files.extend(
            sorted(
                f
                for f in glob.glob(os.path.join(root, project, "*.jl"))
                if f.endswith(EMAIL_ENTITY_SUFFIXES)
            )
        )
    if not files:
        raise SystemExit(f"No email-entity .jl files found under {root}")
    return files


def _flat_email(
    *,
    urn_suffix: str,
    project: str,
    subject: str,
    body_text: str,
    from_val: str | None,
    date: str | None,
    message_id: str | None,
    in_reply_to: str | None,
    entity_type: str,
    original_id: str | None,
) -> dict[str, Any]:
    """Build an OCEAN-shaped flat email doc (urn/wiki + flat fields)."""
    urn = f"curatedemail:{project}:{urn_suffix}"
    headers: dict[str, Any] = {}
    for k, v in [
        ("message_id", message_id),
        ("subject", subject),
        ("date", date),
        ("in_reply_to", in_reply_to),
    ]:
        if v is not None:
            headers[k] = v
    if from_val:
        headers["from"] = from_val
    flat = {
        "subject": subject,
        "body_text": body_text,
        "raw_from_string": from_val,
        "raw_date_string": date,
        "message_id": message_id,
        "in_reply_to": in_reply_to,
        "group": project,
    }
    return {
        "urn": urn,
        **flat,
        "headers": headers,
        "lang": "en",
        "platform_id": PLATFORM_ID,
        "corpus_id": CORPUS_ID,
        "venue_id": f"{PLATFORM_ID}:{CORPUS_ID}:{project}",
        "artefact_kind": "email",
        "artefact_labels": ["Artefact", "MessageArtefact", "EmailMessage"],
        "metadata": {
            "entity_type": entity_type,
            "original_id": original_id,
            "project": project,
        },
        "_meta": {
            "item_type": "email",
            "corpus_id": CORPUS_ID,
            "platform_id": PLATFORM_ID,
            "record_id": urn,
            "group": project,
            "mined_at": "",
            "processed": False,
            "content_sha256": content_sha256(flat),
        },
    }


def iter_records(
    path: str, *, sample_rate: float = 1.0, max_words: int | None = DEFAULT_MAX_WORDS
) -> Iterator[dict[str, Any]]:
    """
    Yield one OCEAN-shaped email doc per record from a Patchwork entity file.
    Resilient to malformed lines. `subject` is required for a record to become
    a TextUnit-bearing email (no-subject records are dropped with a warning).
    Applies deterministic hash-based subsampling when `sample_rate < 1.0`.

    Records whose body exceeds `max_words` whitespace tokens are dropped with a
    warning: such bodies are embedded patches/logs, and the raw doc they produce
    can exceed Mongo's 16 MiB BSON limit and fail the entire bulk batch. Pass
    `max_words=None` (or a non-positive value) to disable the guard.
    """
    import hashlib
    import json

    basename = os.path.basename(path)
    project = os.path.basename(os.path.dirname(path))
    entity_type = basename.split("_", 1)[-1].rsplit(".", 1)[0]
    guard_on = max_words is not None and max_words > 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue

            # Deterministic hash sampling across the entity file
            if sample_rate < 1.0:
                h_str = hashlib.md5(f"{project}:{basename}:{line_no}".encode()).hexdigest()[:8]
                h = int(h_str, 16) % 10000
                if (h / 10000.0) >= sample_rate:
                    continue

            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("%s:%d malformed JSON (%s)", path, line_no, exc)
                continue
            original_id = rec.get("original_id")
            if entity_type == "mailinglist":
                subject, body = rec.get("subject", ""), rec.get("content", "")
                in_reply_to = None
            elif entity_type == "comment":
                subject, body = rec.get("subject", ""), rec.get("msg_content", "")
                in_reply_to = rec.get("in_reply_to")
            elif entity_type == "patch":
                # code_diff is code, not authored epistemic discourse → excluded.
                subject, body = rec.get("name") or "", rec.get("msg_content") or ""
                in_reply_to = rec.get("in_reply_to")
            elif entity_type == "series":
                subject, body = rec.get("name") or "", rec.get("cover_letter_content") or ""
                in_reply_to = None
            else:
                continue
            if not subject:
                logger.debug("Dropping %s record without subject: %s", entity_type, original_id)
                continue
            body = body or ""
            if guard_on and len(body.split()) > max_words:
                # Fast path: a body of <= max_words characters can never exceed
                # max_words tokens, so the split() list allocation below only
                # runs for genuinely long bodies (CHANGELOG 2026-08-18).
                n_words = len(body.split())
                if n_words > max_words:
                    logger.warning(
                        "%s:%d dropping oversized %s record %s (%d words > %d threshold)",
                        path,
                        line_no,
                        entity_type,
                        original_id or f"{project}-{entity_type}-{line_no}",
                        n_words,
                        max_words,
                    )
                    continue
            key = original_id or f"{project}-{entity_type}-{line_no}"
            yield _flat_email(
                urn_suffix=key,
                project=project,
                subject=subject,
                body_text=body,
                from_val=rec.get("sender_name"),
                date=rec.get("date"),
                message_id=rec.get("msg_id"),
                in_reply_to=in_reply_to,
                entity_type=entity_type,
                original_id=original_id,
            )


def _event_for(doc: dict[str, Any], mongo_id: str) -> dict[str, Any]:
    return external_event(
        "email",
        f"curatedemail:{doc['group']}",
        mongo_id,
        platform_id=PLATFORM_ID,
        corpus_id=CORPUS_ID,
        venue_id=doc["venue_id"],
        artefact_kind="email",
        artefact_labels=doc["artefact_labels"],
    )


async def ingest(
    root: str | None = None,
    projects: list[str] | None = None,
    max_records: int | None = None,
    dry_run: bool = False,
    sample_rates: dict[str, float] | None = None,
    max_words: int | None = DEFAULT_MAX_WORDS,
) -> int:
    root = root or os.path.join(settings.datasets_root, "Curated Email-Based Code Reviews Datasets")
    projects = projects or ["ffmpeg", "kernel", "ozlabs"]
    files = iter_email_files(root, projects)
    rates = sample_rates if sample_rates is not None else DEFAULT_SAMPLE_RATES

    def gen() -> Iterator[dict[str, Any]]:
        for path in files:
            project = os.path.basename(os.path.dirname(path))
            rate = rates.get(project, 1.0)
            yield from iter_records(path, sample_rate=rate, max_words=max_words)

    return await run_external_ingest(
        docs=gen(),
        collection=EMAIL_COLLECTION,
        key_field="urn",
        event_for=_event_for,
        label="Ingest curated email code reviews",
        max_records=max_records,
        dry_run=dry_run,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    )
    p = argparse.ArgumentParser(description="Ingest curated email code-review datasets.")
    p.add_argument("--path", default=None)
    p.add_argument("--projects", nargs="*", default=None)
    p.add_argument(
        "--sample-rate",
        type=float,
        default=None,
        help="Uniform sample rate (0.0-1.0) across all projects.",
    )
    p.add_argument(
        "--sample-rates",
        nargs="*",
        default=None,
        help="Per-project rates, e.g. ffmpeg=1.0 ozlabs=0.4484 kernel=0.4484",
    )
    p.add_argument("--max", type=int, default=None)
    p.add_argument(
        "--max-words",
        type=int,
        default=DEFAULT_MAX_WORDS,
        help=(
            f"Skip records whose body exceeds this many words "
            f"(default: {DEFAULT_MAX_WORDS}; 0 or negative disables)."
        ),
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sample_rates = None
    all_projects = args.projects or ["ffmpeg", "kernel", "ozlabs"]
    if args.sample_rate is not None:
        sample_rates = {prj: args.sample_rate for prj in all_projects}
    elif args.sample_rates:
        sample_rates = {}
        for pair in args.sample_rates:
            if "=" in pair:
                k, v = pair.split("=", 1)
                sample_rates[k.strip()] = float(v.strip())

    max_words = args.max_words if args.max_words is not None and args.max_words > 0 else None
    asyncio.run(
        ingest(
            root=args.path,
            projects=args.projects,
            max_records=args.max,
            dry_run=args.dry_run,
            sample_rates=sample_rates,
            max_words=max_words,
        )
    )


if __name__ == "__main__":
    main()
