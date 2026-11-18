"""
Jira Ingester — Apache Jira and the Alternative Jira dataset (v0.8).

Two independent corpora, both represented as :JiraIssue under their own
corpus/venue namespace (a Jira issue is comparable to a GitHub issue only
through the shared :Artefact:IssueArtefact layer — never by reusing the GitHub
Issue node, whose key is (repo, number)).

1. Apache Jira (MSR 2023 Jira Issues Dataset):
   /Volumes/Samsung SSD 990 PRO 4TB/Graph_NK_datasets/apache_jira_dataset/
     issues.bson.gz, comments.bson.gz, projects.bson.gz  (gzip of BSON stream)
   Issues have `key` (e.g. "ACCUMULO-123"), `summary`, `description`, `status`;
   comments are a separate BSON file keyed on `issue`. We stream gzip+BSON
   (never materialising the whole file), collect issues by key, and attach
   their comments. corpus_id "apache-jira".

2. Alternative Jira (Montgomery, Lueders, Maalej, MSR 2022):
   /Volumes/Samsung SSD 990 PRO 4TB/Graph_NK_datasets/TheAlternativeJiraDataset/
     3. DataDump/mongodump-JiraReposAnon.archive  (gzip'ed mongodump archive)
   PREREQUISITE: restore the archive into the local MongoDB first (the Mongo
   being restored here is the pipeline's local instance at localhost:27017):
       mongorestore --gzip --archive=mongodump-JiraReposAnon.archive
   The archive holds ONE collection per Jira instance (Apache, MongoDB, Qt,
   RedHat, Spring, ...). The ingester streams every collection (or the
   --collections subset) directly from MongoDB via --db/--collections.
   corpus_id "alternative-jira". Docs are raw Jira REST /search JSON: the
   issue `key` is top-level, everything else is nested under `fields`
   (fields.summary, fields.description, ...); they are mapped through the
   ALTI_FIELD_MAP below (a config edit, not a refactor).

SCOPE (agreed with the researcher): only summary (title), description (body),
and comment bodies become TextUnits. Changelogs, worklogs, issue links, topic
probabilities and custom fields are OUT OF SCOPE.

Usage:
    # Apache
    python -m miner.jira_ingester --corpus apache --path <dir> [--max N] [--dry-run]
    # Alternative (after mongorestore)
    python -m miner.jira_ingester --corpus alternative \
        --db JiraReposAnon [--collections Apache MongoDB ...] [--max N] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import logging
import os
from typing import Any

import bson

from miner.external_common import (
    EXTERNAL_COLLECTION,
    external_event,
    issue_doc,
    make_record_id,
    namespaced_login,
    run_external_ingest,
)
from settings import settings

logger = logging.getLogger("miner.jira")

PLATFORM_ID = "jira"
LABELS_ISSUE = ["Artefact", "IssueArtefact", "JiraIssue"]
CORPUS_APACHE = "apache-jira"
CORPUS_ALT = "alternative-jira"

CORPORA = {
    "apache": {
        "corpus_id": "apache-jira",
        "dir": "apache_jira_dataset",
        "issues_bson": "issues.bson.gz",
        "comments_bson": "comments.bson.gz",
    },
    "alternative": {
        "corpus_id": "alternative-jira",
        "dir": "TheAlternativeJiraDataset/DataDump",
    },
}

# Alternative Jira: source key paths for the text we extract, per issue doc.
#
# The dataset stores raw Jira REST /search JSON: the issue `key` is top-level,
# everything else lives under `fields` (see the module docstring and CHANGELOG
# 2026-08-19). Each entry is a list of candidate paths; the first one that
# resolves to a non-null value is used. Adjust this map if a restored instance
# differs (this is the intended config seam — see the module docstring).
ALTI_FIELD_MAP = {
    "key": [["key"]],
    "summary": [["fields", "summary"]],
    "description": [["fields", "description"]],
    "status": [["fields", "status", "name"]],
    "creator": [["fields", "creator"]],
    "reporter": [["fields", "reporter"]],
    "created": [["fields", "created"]],
    "project": [["fields", "project", "name"], ["fields", "project", "key"]],
    "comments": [["fields", "comments"]],
}


def _snake(name: str) -> str:
    return name.strip().lower().replace(" ", "-").replace("/", "-")


def iter_apache_bson_records(path: str):
    """Yield one dict per BSON document from a gzip'ed BSON stream (streaming)."""
    with gzip.open(path, "rb") as fh:
        yield from bson.decode_file_iter(fh)


def _apache_author(author: Any) -> str | None:
    if isinstance(author, dict):
        return (author.get("name") or author.get("displayName") or "").strip() or None
    if isinstance(author, str):
        return author.strip() or None
    return None


def _apache_status(status: Any) -> str | None:
    return (status.get("name") if isinstance(status, dict) else str(status or "")).strip() or None


def iter_apache_issues_docs(root: str) -> dict[str, dict[str, Any]]:
    """Collect Apache Jira issues (key → issue_doc with empty comments)."""
    issues_path = os.path.join(root, CORPORA["apache"]["issues_bson"])
    issues: dict[str, dict[str, Any]] = {}
    for raw in iter_apache_bson_records(issues_path):
        key = raw.get("key") or raw.get("id")
        if not key:
            continue
        project = raw.get("projectname") or "unknown"
        venue_id = f"{PLATFORM_ID}:{CORPUS_APACHE}:{_snake(project)}"
        record_id = make_record_id("jira_issue", CORPUS_APACHE, key)
        issues[key] = issue_doc(
            record_id=record_id,
            external_id=str(key),
            title=raw.get("summary") or "",
            body=raw.get("description") or "",
            comments=[],
            author_login=namespaced_login(
                PLATFORM_ID, CORPUS_APACHE, _apache_author(raw.get("reporter"))
            ),
            created_at=raw.get("created"),
            platform_id=PLATFORM_ID,
            corpus_id=CORPUS_APACHE,
            venue_id=venue_id,
            artefact_kind="jira_issue",
            labels=LABELS_ISSUE,
            state=_apache_status(raw.get("status")),
            source_file=os.path.basename(issues_path),
            metadata={
                "jira_key": key,
                "issuetype": (
                    (raw.get("issuetype", {}) or {}).get("name")
                    if isinstance(raw.get("issuetype"), dict)
                    else raw.get("issuetype")
                ),
                "priority": (
                    (raw.get("priority", {}) or {}).get("name")
                    if isinstance(raw.get("priority"), dict)
                    else raw.get("priority")
                ),
                "resolution": (
                    (raw.get("resolution", {}) or {}).get("name")
                    if isinstance(raw.get("resolution"), dict)
                    else raw.get("resolution")
                ),
                "labels": raw.get("labels") or [],
                "components": raw.get("components") or [],
            },
        )
    return issues


def attach_apache_comments(issues: dict[str, dict[str, Any]], root: str) -> None:
    """Attach comments.bson records (keyed on 'issue') to their issue docs."""
    comments_path = os.path.join(root, CORPORA["apache"]["comments_bson"])
    attached = orphan = 0
    for c in iter_apache_bson_records(comments_path):
        issue_key = c.get("issue")
        if issue_key not in issues:
            orphan += 1
            continue
        issues[issue_key]["comments"].append(
            {
                "body": c.get("body") or "",
                "author_login": namespaced_login(
                    PLATFORM_ID, CORPUS_APACHE, _apache_author(c.get("author"))
                ),
                "created_at": c.get("created"),
            }
        )
        attached += 1
    logger.info("Apache comments: attached %d, orphaned %d (no such issue key).", attached, orphan)


def _alt_get(doc: dict[str, Any], *paths: list[str]) -> Any:
    """First non-null value along any of the given nested key paths."""
    for path in paths:
        v: Any = doc
        for key in path:
            if not isinstance(v, dict) or key not in v:
                v = None
                break
            v = v[key]
        if v is not None and v != "" and v != []:
            return v
    return None


def _alt_author_name(author: Any) -> str | None:
    """
    Extract a stable author string from an Alternative Jira field.

    Different Jira instances store the creator/reporter either as a plain string
    ("johndoe") or as a user dict ({"name": "...", "displayName": "..."}). The
    pre-fix code passed the raw value to namespaced_login, whose sanitise_token
    stringified a dict into something like "-name-:-johndoe-" (CHANGELOG
    2026-08-19). Prefer the machine-readable `name`/`username`/`key` over the
    display name so the login is stable across the corpus.
    """
    if isinstance(author, dict):
        for key in ("name", "username", "key", "displayName"):
            v = author.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None
    if isinstance(author, str):
        return author.strip() or None
    return None


def normalize_alternative_doc(raw: dict[str, Any], instance: str) -> dict[str, Any] | None:
    """Map a raw Alternative Jira issue doc → issue_doc (via ALTI_FIELD_MAP).

    `instance` is the restored collection name (the Jira instance in the
    dataset, e.g. "MongoDB"); it goes into the record_id and venue_id so issue
    keys that collide across Jira instances ("SPRING-1" etc.) cannot overwrite
    each other on the raw_external record_id key (CHANGELOG 2026-08-19).
    """
    key = _alt_get(raw, *ALTI_FIELD_MAP["key"]) or raw.get("_id")
    if not key:
        return None
    summary = _alt_get(raw, *ALTI_FIELD_MAP["summary"]) or ""
    description = _alt_get(raw, *ALTI_FIELD_MAP["description"]) or ""
    if not summary and not description:
        return None  # nothing to annotate
    creator = _alt_author_name(
        _alt_get(raw, *ALTI_FIELD_MAP["creator"]) or _alt_get(raw, *ALTI_FIELD_MAP["reporter"])
    )
    project = _alt_get(raw, *ALTI_FIELD_MAP["project"]) or "unknown"
    status = _alt_get(raw, *ALTI_FIELD_MAP["status"])
    created = _alt_get(raw, *ALTI_FIELD_MAP["created"])
    comments_raw = _alt_get(raw, *ALTI_FIELD_MAP["comments"]) or []
    comments = [
        {
            "body": c.get("body") if isinstance(c, dict) else str(c),
            "author_login": namespaced_login(
                PLATFORM_ID, CORPUS_ALT, _alt_author_name(c.get("author")) or creator
            ),
            "created_at": c.get("created") if isinstance(c, dict) else None,
        }
        for c in comments_raw
        if isinstance(c, dict) or c
    ]
    venue_id = f"{PLATFORM_ID}:{CORPUS_ALT}:{_snake(instance)}:{_snake(str(project))}"
    record_id = make_record_id("jira_issue", CORPUS_ALT, instance, str(key))
    return issue_doc(
        record_id=record_id,
        external_id=str(key),
        title=summary,
        body=description,
        comments=comments,
        author_login=namespaced_login(PLATFORM_ID, CORPUS_ALT, creator),
        created_at=created,
        platform_id=PLATFORM_ID,
        corpus_id=CORPUS_ALT,
        venue_id=venue_id,
        artefact_kind="jira_issue",
        labels=LABELS_ISSUE,
        state=status,
        metadata={"jira_key": str(key), "jira_instance": instance, **_alt_meta_deep(raw)},
    )


def _alt_meta_deep(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep a shallow snapshot of non-text raw fields for provenance."""
    keep = {}
    for k, v in raw.items():
        if k in ("summary", "description", "comments", "changes", "worklogs"):
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            keep[k] = v
    return keep


def _event_for(corpus_id: str) -> Any:
    def build(doc: dict[str, Any], mongo_id: str) -> dict[str, Any]:
        return external_event(
            "jira_issue",
            doc["venue_id"],
            mongo_id,
            platform_id=PLATFORM_ID,
            corpus_id=corpus_id,
            venue_id=doc["venue_id"],
            artefact_kind="jira_issue",
            artefact_labels=LABELS_ISSUE,
        )

    return build


async def ingest(
    corpus: str,
    root: str | None = None,
    db: str | None = None,
    collections: list[str] | None = None,
    max_records: int | None = None,
    dry_run: bool = False,
) -> int:
    if corpus == "apache":
        root = root or os.path.join(settings.datasets_root, CORPORA["apache"]["dir"])
        issues = iter_apache_issues_docs(root)
        attach_apache_comments(issues, root)
        return await run_external_ingest(
            docs=iter(issues.values()),
            collection=EXTERNAL_COLLECTION,
            key_field="record_id",
            event_for=_event_for(CORPUS_APACHE),
            label="Ingest Apache Jira",
            max_records=max_records,
            dry_run=dry_run,
        )

    # Alternative Jira — requires a restored local Mongo (see module docstring).
    from storage import make_mongo_client

    client = make_mongo_client()
    try:
        db_obj = client[db]
        if collections:
            col_names = collections
        else:
            col_names = await db_obj.list_collection_names()
        if not col_names:
            raise ValueError(
                f"no collections found in db '{db}' — did you restore the mongodump archive first?"
            )

        async def gen():
            for col_name in col_names:
                async for raw in db_obj[col_name].find():
                    doc = normalize_alternative_doc(raw, col_name)
                    if doc is not None:
                        yield doc

        return await run_external_ingest(
            docs=gen(),
            collection=EXTERNAL_COLLECTION,
            key_field="record_id",
            event_for=_event_for(CORPUS_ALT),
            label="Ingest Alternative Jira",
            max_records=max_records,
            dry_run=dry_run,
        )
    finally:
        client.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    )
    p = argparse.ArgumentParser(description="Ingest Apache / Alternative Jira datasets.")
    p.add_argument("--corpus", choices=["apache", "alternative"], required=True)
    p.add_argument("--path", default=None, help="Apache dataset dir.")
    p.add_argument("--db", default="JiraReposAnon", help="Alternative restored Mongo db.")
    p.add_argument(
        "--collections",
        nargs="+",
        default=None,
        help="Alternative Jira instance collection(s) to ingest (default: all).",
    )
    p.add_argument("--max", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    asyncio.run(
        ingest(
            args.corpus,
            root=args.path,
            db=args.db,
            collections=args.collections,
            max_records=args.max,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
