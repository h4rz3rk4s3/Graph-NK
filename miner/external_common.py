"""
Shared helpers for the curated-MSR-dataset ingesters (v0.8).

Everything here is format-independent glue that the per-dataset ingesters in
miner/ reuse so that ID construction, provenance metadata, and pointer-event
publishing stay uniform across corpora. Format-specific readers live in the
individual ingesters — do NOT add dataset format parsers to this module
(FRAMEWORK_DESIGN.md §12; AGENTS.md §5.6).

Two invariants every ingester must uphold (see FRAMEWORK_DESIGN.md §4.8):
  1. Every normalized Mongo doc carries the common artefact fields
     (record_id, platform_id, venue_id, corpus_id/source_corpus, artefact_kind,
     author_login, created_at, metadata) so the projector can seed
     :Artefact + family + platform labels without dataset-specific branches.
  2. record_id is globally namespaced and is used BOTH as the Mongo unique key
     and as the TextUnit parent_id — never derive it by splitting strings.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Single Mongo collection for all external (non-GitHub-shaped) artefacts,
# keyed on `record_id`. GitHub-shaped corpora (OpenMent, NumFocus) reuse the
# existing raw_issues/raw_pull_requests/raw_commits collections.
EXTERNAL_COLLECTION = "raw_external"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str, *, max_len: int = 60) -> str:
    """Lowercase, non-alphanumeric→'-', truncate. For corpus/venue slugs."""
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug[:max_len].rstrip("-")


def sanitise_token(value: Any) -> str:
    """Collapse any external id (incl. None/slashes/whitespace) to a safe token."""
    s = str(value).strip().replace("/", "-").replace("\\", "-")
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^A-Za-z0-9_.:+~-]", "", s)  # allow ':' for urn-like ids inside parts
    return s or "unknown"


def content_sha256(doc: dict[str, Any] | list | str) -> str:
    """Stable sha256 over the source document (JSON, sort_keys, str coercion)."""
    payload = json.dumps(doc, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def build_meta(
    item_type: str,
    *,
    corpus_id: str,
    record_id: str,
    platform_id: str,
    source_file: str = "",
) -> dict[str, Any]:
    """Standard _meta block carried on every external raw doc."""
    return {
        "item_type": item_type,
        "corpus_id": corpus_id,
        "platform_id": platform_id,
        "record_id": record_id,
        "source_file": source_file,
        "mined_at": utc_now_iso(),
        "processed": False,
    }


def external_event(
    item_type: str,
    repo_name: str,
    mongo_id: str,
    *,
    platform_id: str,
    corpus_id: str,
    venue_id: str,
    artefact_kind: str,
    artefact_labels: list[str] | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """
    Build the stream_raw pointer event for one persisted external document.

    The extra fields (platform_id / corpus_id / venue_id / artefact_kind /
    artefact_labels / conversation_id) are consumed by the projector's
    upsert_artefact_from_raw so Phase-0 seeding can apply the right labels and
    containers without inspecting the Mongo doc again. The `repo_name` field
    keeps the existing stream contract (venue namespace, same as the OCEAN
    "ocean:<list>" precedent) so annotators/base.py::TextUnit is unchanged.
    """
    event: dict[str, Any] = {
        "item_type": item_type,
        "item_subtype": item_type,
        "repo_name": repo_name,
        "mongo_id": str(mongo_id),
        "platform_id": platform_id,
        "corpus_id": corpus_id,
        "venue_id": venue_id,
        "artefact_kind": artefact_kind,
    }
    if artefact_labels:
        event["artefact_labels"] = list(artefact_labels)
    if conversation_id:
        event["conversation_id"] = conversation_id
    return event


def namespaced_login(platform_id: str, corpus_id: str, external_id: Any) -> str:
    """
    Deterministic Actor login for external/anonymized identities.

    The existing Actor.login uniqueness constraint stays overloaded on purpose
    (gmane precedent already stores anonymized senders as login); namespacing
    is the ingester's job so 'Melvin' in one corpus cannot collide with
    'Melvin' in another. Cross-platform identity resolution is out of scope.
    """
    return f"{platform_id}:{slugify(corpus_id, max_len=24)}:{sanitise_token(external_id)}"


def make_record_id(prefix: str, corpus_id: str, *parts: Any) -> str:
    """Namespaced, collision-safe external record id.

        >>> make_record_id("jira_issue", "apachejira", "HBASE-1234")
        "jira_issue:apachejira:HBASE-1234"

    The prefix is the parent_type; corpus_id is the corpus slug; parts are the
    dataset-internal identifiers joined by ':'.
    """
    token_parts = ":".join(sanitise_token(p) for p in parts)
    return f"{prefix}:{slugify(corpus_id)}:{token_parts}"


def data_path_parts(path: str, marker: str = "data") -> tuple[str, str, str]:
    """
    Split a corpus file path into (community, period, filename).

    DISCO and Slack both live at <root>/data/<community>/<period>/<file>, but the
    record iterators only receive `path` and the dataset root varies, so the
    extraction keys on the LAST `marker` path component instead of assuming a
    root location. The pre-fix code cut the relative path one directory short,
    swapping community and period (CHANGELOG 2026-08-19). Falls back to
    ("unknown", "unknown") when no `marker` component exists, mirroring the
    original degenerate-path handling.
    """
    parts = path.split(os.sep)
    idx = max((i for i, part in enumerate(parts) if part == marker), default=-1)
    rel = parts[idx + 1 :] if idx >= 0 else []
    if len(rel) > 1:
        return rel[0], rel[1], rel[-1]
    return "unknown", "unknown", os.path.basename(path)


def _base_artefact(
    *,
    record_id: str,
    platform_id: str,
    corpus_id: str,
    venue_id: str,
    artefact_kind: str,
    author_login: str | None,
    created_at: str | None,
    labels: list[str],
    source_file: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Common fields for every normalized external raw doc (v0.8)."""
    return {
        "record_id": record_id,
        "platform_id": platform_id,
        "corpus_id": corpus_id,
        "venue_id": venue_id,
        "artefact_kind": artefact_kind,
        "artefact_labels": list(labels),
        "author_login": author_login,
        "created_at": created_at,
        "source_file": source_file,
        "metadata": metadata or {},
        "_meta": build_meta(
            artefact_kind_to_item_type(artefact_kind),
            corpus_id=corpus_id,
            record_id=record_id,
            platform_id=platform_id,
            source_file=source_file,
        ),
    }


def artefact_kind_to_item_type(artefact_kind: str) -> str:
    """Map artefact_kind back to the stream_raw item_type (parent_type)."""
    if artefact_kind.startswith("so_"):
        return "so_post"
    if artefact_kind in ("jira_issue", "bugzilla_issue", "chat", "irc"):
        return {
            "jira_issue": "jira_issue",
            "bugzilla_issue": "bugzilla_issue",
            "chat": "chat_message",
            "irc": "chat_message",
        }.get(artefact_kind, "chat_message")
    raise ValueError(f"Unexpected artefact_kind {artefact_kind!r} for external doc")


def chat_doc(
    *,
    record_id: str,
    text: str,
    author_login: str | None,
    created_at: str | None,
    channel: str,
    sequence: int | None,
    platform_id: str,
    corpus_id: str,
    venue_id: str,
    labels: list[str],
    conversation_id: str | None = None,
    reply_to: list[str] | str | None = None,
    source_file: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalized chat/IRC/Slack/Discord/Gitter message doc (section 3.14.3)."""
    doc = _base_artefact(
        record_id=record_id,
        platform_id=platform_id,
        corpus_id=corpus_id,
        venue_id=venue_id,
        artefact_kind="chat",
        author_login=author_login,
        created_at=created_at,
        labels=labels,
        source_file=source_file,
        metadata=metadata,
    )
    doc.update(
        {
            "text": text,
            "channel": channel,
            "sequence": sequence,
            "conversation_id": conversation_id,
        }
    )
    if reply_to:
        doc["reply_to"] = reply_to
    return doc


def issue_doc(
    *,
    record_id: str,
    external_id: str,
    title: str | None,
    body: str | None,
    comments: list[dict[str, Any]],
    author_login: str | None,
    created_at: str | None,
    platform_id: str,
    corpus_id: str,
    venue_id: str,
    artefact_kind: str,
    labels: list[str],
    state: str | None = None,
    source_file: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalized Jira/Bugzilla issue doc (section 3.14.2)."""
    doc = _base_artefact(
        record_id=record_id,
        platform_id=platform_id,
        corpus_id=corpus_id,
        venue_id=venue_id,
        artefact_kind=artefact_kind,
        author_login=author_login,
        created_at=created_at,
        labels=labels,
        source_file=source_file,
        metadata=metadata,
    )
    doc.update(
        {
            "external_id": external_id,
            "title": title,
            "body": body,
            "comments": comments,
            "state": state,
        }
    )
    return doc


class _MaxReached(Exception):
    """Internal flow control for --max."""


async def _flush(
    coll: Any,
    broker: Any,
    batch: list[dict[str, Any]],
    key_field: str,
    event_for: Any,
) -> int:
    """Bulk-upsert one batch to Mongo; publish pointer events for NEW docs only."""
    from settings import settings
    from storage import bulk_upsert_on_key

    new_docs = await bulk_upsert_on_key(coll, batch, key_field)
    for doc in new_docs:
        event = event_for(doc, str(doc["_id"]))
        await broker.publish(settings.stream_raw, event)
    return len(new_docs)


async def run_external_ingest(
    *,
    docs: Any,
    collection: str,
    key_field: str,
    event_for: Any,
    label: str = "Ingest",
    filter_fn: Any = None,
    max_records: int | None = None,
    dry_run: bool = False,
    batch_size: int | None = None,
) -> int:
    """
    Shared pipeline for the curated-dataset ingesters.

    Iterates normalized `docs`, applies the optional `filter_fn`, bulk-upserts
    to Mongo keyed on `key_field`, and publishes a stream_raw pointer event for
    each NEWLY persisted doc (via `event_for(doc, mongo_id)`). This mirrors the
    OCEAN/Gmane contract (Mongo first, then the pointer) so the extractor →
    annotator → projector pipeline runs unchanged.

    `dry_run=True` parses and reports only; nothing is written and no services
    are contacted — used for bounded, read-only validation (`--dry-run --max N`).

    Returns the number of records kept (persisted, or counted in dry-run).
    """
    kept = scanned = 0

    async def _iter_docs():
        """Yield docs whether `docs` is a sync or an async iterator."""
        if hasattr(docs, "__aiter__"):
            async for doc in docs:
                yield doc
        else:
            for doc in docs:
                yield doc

    if dry_run:
        async for doc in _iter_docs():
            scanned += 1
            if filter_fn is not None and not filter_fn(doc):
                continue
            kept += 1
            if max_records is not None and kept >= max_records:
                break
        logger.info(
            "%s: DRY-RUN — %d kept / %d scanned (no writes performed).",
            label,
            kept,
            scanned,
        )
        return kept

    from broker import get_broker
    from progress import Progress
    from settings import settings
    from storage import make_mongo_client

    mongo = make_mongo_client()
    db = mongo[settings.mongo_db_name]
    coll = db[collection]
    await coll.create_index(key_field, unique=True)
    broker = await get_broker()
    prog = Progress(label)
    bs = batch_size or getattr(settings, "gmane_batch_size", 2000)
    # Bound the batch to `--max` when it is smaller than the default batch, so a
    # bounded debug run does not over-shoot the target by a whole batch.
    if max_records is not None:
        bs = min(bs, max_records)
    batch: list[dict[str, Any]] = []

    async def _flush_batch() -> None:
        """Flush the current batch and advance progress by the DOCS PROCESSED
        (len(batch)), not the cumulative `kept` total. Progress.done is a
        monotone count of work done; adding the cumulative total each flush
        grows it quadratically and inflates the reported rate (CHANGELOG
        2026-08-19)."""
        nonlocal kept
        batch_len = len(batch)
        kept += await _flush(coll, broker, batch, key_field, event_for)
        batch.clear()
        prog.add(batch_len)

    try:
        async for doc in _iter_docs():
            scanned += 1
            if filter_fn is not None and not filter_fn(doc):
                continue
            batch.append(doc)
            if len(batch) >= bs:
                await _flush_batch()
                prog.maybe_log()
                if max_records is not None and kept >= max_records:
                    logger.info("%s: reached --max %d; stopping.", label, max_records)
                    raise _MaxReached
        if batch:
            await _flush_batch()
            prog.maybe_log()
    except _MaxReached:
        pass
    finally:
        prog.finish()
        mongo.close()
        logger.info("%s done: %d persisted (new) / %d scanned.", label, kept, scanned)
        if kept == 0 and scanned > 0:
            # Nothing new written: the records are already in MongoDB (idempotent
            # re-run). This is NOT an error, but users read "0 persisted" as a
            # failure — and because Redis is non-persistent (CHANGELOG 2026-08-16),
            # re-running the ingester does NOT repopulate stream_raw either. Point
            # at the rebuild path so the queue can be restored explicitly.
            logger.info(
                "%s: 0 new records — all %d scanned records already exist in "
                "MongoDB '%s'. To (re)load them into the Redis pipeline queue, "
                "run: python scripts/republish_events.py",
                label,
                scanned,
                collection,
            )
    return kept
