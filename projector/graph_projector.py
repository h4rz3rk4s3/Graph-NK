"""
Module 4 — GraphProjector.

The ONLY module allowed to write Cypher. All annotators emit plain Signal dicts;
this module decides how they become nodes and edges in Neo4j.

Cypher templates mirror ontology/ontology.cypher §3 exactly.
Any ontology change requires updating both files — see AGENTS.md §5.6.

See FRAMEWORK_DESIGN.md §5 Module 4; BUILD_SPEC.md §6 M3.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from settings import settings

logger = logging.getLogger(__name__)

# Threading-header sanitizer (CHANGELOG 2026-08-24).
# The curated email corpora carry `in_reply_to` as EITHER a single string OR a
# list of ancestor message-ids (the Patchwork review / cover-letter chain).
# Two problems follow: (1) Neo4j RANGE indexes cap an indexed property at ~8 KB
# (`email_in_reply_to`, ontology.cypher), so an oversized list aborts the whole
# Phase-1 batch with "Property value is too large to index"; (2) the threading
# enrichment matches `parent.message_id = reply.in_reply_to` exactly, so a list
# value silently yields zero REPLIES_TO edges. We therefore interpret the field
# defensively and deterministically at the projection boundary (Mongo keeps the
# verbatim source — AGENTS.md §1 traceability): a single distinct bracketed id
# (after removing the message's own id) is the direct parent; otherwise the ids
# move to `references` (not indexed, so exempt from the size cap). See CHANGELOG
# 2026-08-24 for the measured distribution (25,670 list records; 22,746
# single-distinct / 2,924 multi; 131 self-inclusions; 21,450 strings with
# surrounding whitespace).
_IN_REPLY_TO_TOKEN = re.compile(r"<[^<>]+>")


def _sanitize_email_threading(
    message_id: Any, in_reply_to: Any, references: Any
) -> tuple[Any, Any, Any]:
    """
    Normalize (message_id, in_reply_to, references) so EmailMessage properties
    are safe to index and thread correctly.

    `in_reply_to` may be None, str (possibly whitespace-padded, possibly
    containing several bracketed ids), or list[str]. Returns a tuple where
    in_reply_to is a single bracketed id when determinable, else None with the
    ancestor ids preserved on `references`.
    """
    message_id = message_id.strip() if isinstance(message_id, str) else message_id

    if isinstance(in_reply_to, str):
        if not in_reply_to.strip():
            return message_id, None, references
        tokens = _IN_REPLY_TO_TOKEN.findall(in_reply_to)
        if not tokens:
            # No angle brackets (e.g. a bare id); keep the stripped string.
            return message_id, in_reply_to.strip(), references
        candidates = [t.strip() for t in tokens]
    elif isinstance(in_reply_to, list):
        candidates = [
            t.strip()
            for entry in in_reply_to
            if isinstance(entry, str)
            for t in _IN_REPLY_TO_TOKEN.findall(entry.strip())
        ]
    else:
        candidates = []

    # A message is never its own In-Reply-To (RFC 5322).
    own = message_id if isinstance(message_id, str) else None
    if own:
        candidates = [c for c in candidates if c != own]

    uniq = list(dict.fromkeys(candidates))  # order-preserving dedupe
    if len(uniq) == 1:
        if len(uniq[0]) > 998:
            # Overlong single id: demote to references rather than risk the
            # index size cap or store a truncated edge target.
            return message_id, None, [uniq[0]] if references is None else references
        return message_id, uniq[0], references
    if uniq:
        return message_id, None, uniq if references is None else references
    return message_id, None, references


class GraphProjector:
    """Wraps all Cypher writes for the GraphRAG-NK ontology."""

    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver
        # Phase-0 memoization (Tier 3, CHANGELOG 2026-08-16): the container
        # chain (_ensure_platform_venue_corpus), Actor, and Repository MERGEs
        # are pure idempotent upserts re-executed for every artefact of a corpus
        # (millions of issues vs. a handful of venues). Remembering which keys
        # were already seeded skips those redundant round trips, which are the
        # dominant cost of Phase 0. THESE THREE MUST REMAIN PURE IDEMPOTENT
        # UPSERTS — no non-deterministic SET (datetime(), randomUUID()) — or
        # the memo silently changes results.
        self._seen_venues: set[tuple[str, str, str]] = set()
        self._seen_actors: set[str] = set()
        self._seen_repos: set[str] = set()

    @classmethod
    async def create(cls) -> GraphProjector:
        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        proj = cls(driver)
        if settings.apply_schema_on_startup:
            await proj.ensure_schema()
        return proj

    async def ensure_schema(self) -> None:
        """
        Apply the constraints + indexes from ontology/ontology.cypher.

        Extracts only the CREATE CONSTRAINT / CREATE INDEX statements (the
        parameterized MERGE templates in that file are skipped), so the schema
        has a single source of truth. Every statement is idempotent
        (IF NOT EXISTS), so this is safe to run on every startup — and it means
        the indexes are guaranteed present no matter how Neo4j was launched.
        Without these, MERGE/MATCH degrade to full label scans (the cause of the
        catastrophically slow Phase 1). See CHANGELOG 2026-06-04.
        """
        from pathlib import Path

        ddl_file = Path(__file__).resolve().parent.parent / "ontology" / "ontology.cypher"
        if not ddl_file.exists():
            logger.warning("Schema file %s not found; skipping ensure_schema.", ddl_file)
            return

        statements = []
        for raw in ddl_file.read_text().split(";"):
            lines = [ln for ln in raw.splitlines() if not ln.strip().startswith("//")]
            stmt = "\n".join(lines).strip()
            upper = stmt.upper()
            if upper.startswith("CREATE CONSTRAINT") or upper.startswith("CREATE INDEX"):
                statements.append(stmt)

        for stmt in statements:
            try:
                await self._run(stmt)
            except Exception as exc:
                logger.error("ensure_schema failed on: %s ... (%s)", stmt[:60], exc)
        logger.info("Schema ensured: %d constraints/indexes applied (idempotent).", len(statements))

    async def close(self) -> None:
        await self._driver.close()

    # ── Phase 0 entry point ───────────────────────────────────────────────────

    async def upsert_artefact_from_raw(
        self,
        item_type: str,
        item_subtype: str,
        repo: str,
        doc: dict[str, Any],
        extra: dict[str, Any] | None = None,
    ) -> None:
        """
        Seed Repository / Actor / Issue / PullRequest / Commit / external
        artefact nodes from a raw MongoDB document. Called during Phase 0 of the
        projector worker, before TextUnit nodes are written, so that MATCH
        clauses in upsert_text_unit always find an existing parent node.

        `extra` carries the v0.8 multi-platform fields (platform_id, corpus_id,
        venue_id, artefact_kind, artefact_labels, conversation_id) published by
        the curated-dataset ingesters. When absent (GitHub miner / Gmane /
        OCEAN paths) the artefact is tagged platform='github' or 'mailing_list'
        so the whole graph sits on the shared :Artefact layer (RQ6).

        Fix for CHANGELOG.md ⚠️ limitation 1.
        """
        extra = extra or {}

        # Emails have their own seeding path (MailingList instead of Repository,
        # anonymized `from` header instead of a GitHub user object).
        if item_type == "email":
            await self.upsert_email_message(doc, extra)
            return

        # v0.8 external artefact families — dedicated upserts with their own
        # label sets and containers (no GitHub key assumptions).
        if item_type in ("jira_issue", "bugzilla_issue", "chat_message", "so_post"):
            await self._upsert_external_artefact(item_type, repo, doc, extra)
            return

        # Seed the Actor for the artefact author
        author_obj = doc.get("user") or {}
        if login := author_obj.get("login"):
            await self.upsert_actor(login)

        # Guarantee the Repository node exists (cheap idempotent MERGE).
        # Memoized in Phase 0 (Tier 3, CHANGELOG 2026-08-16): no SET at all, so
        # a repeat MERGE writes nothing; skipping is result-identical.
        if repo and repo not in self._seen_repos:
            await self._run("MERGE (r:Repository {full_name: $repo})", repo=repo)
            # memoise only after a successful write, so a failed write can retry
            self._seen_repos.add(repo)

        if item_type == "repository":
            await self.upsert_repository(doc)
        elif item_subtype == "issue":
            await self.upsert_issue(repo, doc, extra)
        elif item_subtype == "pull_request":
            await self.upsert_pull_request(repo, doc, extra)
        elif item_type == "commit":
            await self.upsert_commit(repo, doc, extra)

    # ── Phase-0 batched seeding ───────────────────────────────────────────────

    async def upsert_artefacts_batch(
        self,
        batch: list[dict[str, Any]],
        docs: dict[str, dict[str, Any]],
    ) -> None:
        """
        Batch Phase-0 artefact seeding (CHANGELOG 2026-08-19).

        Groups the Mongo-fetched `(event, doc)` pairs by artefact family and
        writes each family with ONE `UNWIND` MERGE statement — a handful of Neo4j
        round trips per batch instead of one per event, mirroring
        `upsert_text_units_batch` / `upsert_signals_batch`. On a family failure,
        falls back to the per-item `upsert_artefact_from_raw` so one bad doc does
        not poison the whole family (same pattern as Phase 1).

        The family builders below replicate the per-field derivation from the
        matching single-item upsert; keep them in sync when a derivation changes.
        """
        if not batch:
            return
        pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for event in batch:
            doc = docs.get(event.get("mongo_id"))
            if doc is None:
                logger.warning("Phase 0: doc not found: %s", event.get("mongo_id"))
                continue
            pairs.append((event, doc))
        if not pairs:
            return

        families: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
        for event, doc in pairs:
            families.setdefault(self._artefact_family(event, doc), []).append((event, doc))

        for family, items in families.items():
            try:
                await self._upsert_family_batch(family, items)
            except Exception as exc:
                logger.error(
                    "Phase 0: family %s batch failed (%d): %s — per-item fallback",
                    family,
                    len(items),
                    exc,
                )
                for event, doc in items:
                    await self.upsert_artefact_from_raw(
                        event.get("item_type", ""),
                        event.get("item_subtype", event.get("item_type")),
                        event.get("repo_name", ""),
                        doc,
                        extra=event,
                    )

    @staticmethod
    def _artefact_family(event: dict[str, Any], doc: dict[str, Any]) -> str:
        """Buckets an event into the family whose batch builder writes it."""
        item_type = event.get("item_type", "")
        if item_type in (
            "email",
            "jira_issue",
            "bugzilla_issue",
            "chat_message",
            "so_post",
            "repository",
        ):
            return item_type
        item_subtype = event.get("item_subtype", item_type)
        if item_subtype == "issue":
            return "github_issue"
        if item_subtype == "pull_request":
            return "github_pull_request"
        if item_type == "commit":
            return "github_commit"
        return "unknown"

    async def _upsert_family_batch(
        self, family: str, items: list[tuple[dict[str, Any], dict[str, Any]]]
    ) -> None:
        """Dispatch a family to its batch builder; raise for unknown families so
        the caller's per-item fallback (and per-item no-op) matches old
        behaviour."""
        if family == "email":
            await self._upsert_email_batch(items)
        elif family in ("jira_issue", "bugzilla_issue"):
            label = "JiraIssue" if family == "jira_issue" else "BugzillaIssue"
            await self._upsert_issue_artefact_batch(label, family, items)
        elif family == "chat_message":
            await self._upsert_chat_batch(items)
        elif family == "so_post":
            await self._upsert_so_batch(items)
        elif family == "github_issue":
            await self._upsert_github_issue_batch(items)
        elif family == "github_pull_request":
            await self._upsert_github_pr_batch(items)
        elif family == "github_commit":
            await self._upsert_github_commit_batch(items)
        elif family == "repository":
            for _, doc in items:
                await self.upsert_repository(doc)
        else:
            raise ValueError(f"unknown artefact family: {family}")

    # ── family batch builders (mirror the per-item derivations) ───────────────

    async def _upsert_email_batch(self, items: list[tuple[dict[str, Any], dict[str, Any]]]) -> None:
        """Batch EmailMessage upsert. Mirrors `upsert_email_message`."""
        actors: set[str] = set()
        venues: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        rows: list[dict[str, Any]] = []
        for event, doc in items:
            extra = event
            urn = doc.get("urn") or ""
            if not urn:
                continue
            headers = doc.get("headers") or {}
            group = doc.get("group") or ""
            sender = (headers.get("from") or "").strip()
            corpus_id = extra.get("corpus_id") or (
                doc.get("_meta", {}).get("corpus_id")
                or (
                    "ocean"
                    if str(urn).startswith("ocean:")
                    else ("gmane" if str(urn).startswith("gmane:") else "email")
                )
            )
            platform_id = extra.get("platform_id", "mailing_list")
            venue_id = extra.get("venue_id") or f"{platform_id}:{group or corpus_id}"
            vkey = (platform_id, corpus_id, venue_id, group or corpus_id)
            venues.setdefault(
                vkey,
                {
                    "platform_id": platform_id,
                    "corpus_id": corpus_id,
                    "venue_id": venue_id,
                    "external_id": group or corpus_id,
                    "platform_name": extra.get("platform_name"),
                    "platform_kind": "email",
                    "corpus_name": extra.get("corpus_name"),
                },
            )
            if sender:
                actors.add(sender)
            message_id, in_reply_to, references = _sanitize_email_threading(
                headers.get("message_id"),
                headers.get("in_reply_to"),
                headers.get("references"),
            )
            rows.append(
                {
                    "urn": urn,
                    "message_id": message_id,
                    "subject": headers.get("subject"),
                    "date": headers.get("date"),
                    "group": group,
                    "list_id": headers.get("list_id"),
                    "in_reply_to": in_reply_to,
                    "references": references,
                    "lang": doc.get("lang"),
                    "record_id": f"email:{urn}",
                    "platform_id": platform_id,
                    "venue_id": venue_id,
                    "corpus_id": corpus_id,
                    "sender": sender,
                    "labels": self._final_labels(
                        extra.get("artefact_labels") or ["Artefact", "MessageArtefact"]
                    ),
                }
            )
        await self._ensure_venues(venues)
        for login in actors:
            await self.upsert_actor(login)
        if not rows:
            return
        await self._run(
            """
            UNWIND $rows AS x
            MERGE (e:EmailMessage {urn: x.urn})
              ON CREATE SET e.message_id = x.message_id, e.subject = x.subject,
                            e.date = x.date, e.group = x.group, e.list_id = x.list_id,
                            e.in_reply_to = x.in_reply_to, e.references = x.references,
                            e.lang = x.lang, e.record_id = x.record_id,
                            e.platform_id = x.platform_id, e.venue_id = x.venue_id,
                            e.corpus_id = x.corpus_id, e.source_corpus = x.corpus_id,
                            e.artefact_kind = 'email'
              ON MATCH  SET e.record_id = x.record_id, e.platform_id = x.platform_id,
                            e.venue_id = x.venue_id, e.corpus_id = x.corpus_id,
                            e.source_corpus = x.corpus_id,
                            e.message_id = x.message_id, e.in_reply_to = x.in_reply_to,
                            e.references = x.references
            WITH e, x
            FOREACH(_ IN CASE WHEN x.group IS NOT NULL AND x.group <> '' THEN [1] ELSE [] END |
              MERGE (m:MailingList {name: x.group})
              MERGE (m)-[:CONTAINS]->(e)
            )
            WITH e, x
            OPTIONAL MATCH (a:Actor {login: x.sender})
            FOREACH(_ IN CASE WHEN a IS NOT NULL THEN [1] ELSE [] END |
              MERGE (a)-[:AUTHORED]->(e)
            )
            WITH e, x
            MATCH (v:Venue {venue_id: x.venue_id})
            MERGE (v)-[:CONTAINS]->(e)
            WITH e, x
            SET e:$(x.labels)
            """,
            rows=rows,
        )

    async def _upsert_issue_artefact_batch(
        self,
        node_label: str,
        artefact_kind: str,
        items: list[tuple[dict[str, Any], dict[str, Any]]],
    ) -> None:
        """Batch Jira/Bugzilla issue node upsert. Mirrors `_upsert_issue_artefact`."""
        actor_types: dict[str, str] = {}
        venues: dict[tuple[str, str, str], dict[str, Any]] = {}
        rows: list[dict[str, Any]] = []
        for event, doc in items:
            extra = event
            record_id = doc.get("record_id") or ""
            if not record_id:
                logger.warning("External %s doc without record_id; skipping.", artefact_kind)
                continue
            platform_id = doc.get("platform_id") or extra.get("platform_id") or "unknown"
            corpus_id = doc.get("corpus_id") or extra.get("corpus_id") or "unknown"
            venue_id = doc.get("venue_id") or extra.get("venue_id") or f"{platform_id}:{record_id}"
            created_at = doc.get("created_at") or doc.get("created")
            state = doc.get("state") or doc.get("status") or ""
            external_id = doc.get("external_id") or record_id
            metadata_json = json.dumps(doc.get("metadata") or {}, default=str)
            author = doc.get("author_login")
            vkey = (platform_id, corpus_id, venue_id)
            venues.setdefault(
                vkey,
                {
                    "platform_id": platform_id,
                    "corpus_id": corpus_id,
                    "venue_id": venue_id,
                    "external_id": venue_id,
                    "platform_name": extra.get("platform_name") or doc.get("platform_name"),
                    "platform_kind": extra.get("platform_kind") or doc.get("platform_kind"),
                    "corpus_name": extra.get("corpus_name") or doc.get("corpus_name"),
                },
            )
            if author:
                actor_types[author] = actor_types.get(author, platform_id)
            rows.append(
                {
                    "record_id": record_id,
                    "platform_id": platform_id,
                    "venue_id": venue_id,
                    "corpus_id": corpus_id,
                    "artefact_kind": artefact_kind,
                    "created_at": created_at,
                    "external_id": external_id,
                    "state": state,
                    "metadata_json": metadata_json,
                    "author": author,
                    "labels": self._final_labels(
                        doc.get("artefact_labels") or ["Artefact", "IssueArtefact"]
                    ),
                }
            )
        await self._ensure_venues(venues)
        for login, atype in actor_types.items():
            await self.upsert_actor(login, actor_type=atype)
        if not rows:
            return
        await self._run(
            f"""
            UNWIND $rows AS x
            MERGE (a:{node_label} {{record_id: x.record_id}})
              ON CREATE SET a.platform_id = x.platform_id, a.venue_id = x.venue_id,
                            a.corpus_id = x.corpus_id, a.source_corpus = x.corpus_id,
                            a.artefact_kind = x.artefact_kind, a.created_at = x.created_at,
                            a.external_id = x.external_id, a.state = x.state,
                            a.metadata_json = x.metadata_json
              ON MATCH  SET a.created_at = x.created_at, a.state = x.state,
                            a.external_id = x.external_id
            WITH a, x
            OPTIONAL MATCH (act:Actor {{login: x.author}})
            FOREACH(_ IN CASE WHEN act IS NOT NULL THEN [1] ELSE [] END |
              MERGE (act)-[:AUTHORED]->(a)
            )
            WITH a, x
            MATCH (v:Venue {{venue_id: x.venue_id}})
            MERGE (v)-[:CONTAINS]->(a)
            WITH a, x
            SET a:$(x.labels)
            """,
            rows=rows,
        )

    async def _upsert_chat_batch(self, items: list[tuple[dict[str, Any], dict[str, Any]]]) -> None:
        """Batch ChatMessage node + conversation wiring. Mirrors
        `_upsert_chat_artefact` (conversation kept a separate UNWIND)."""
        actor_types: dict[str, str] = {}
        venues: dict[tuple[str, str, str], dict[str, Any]] = {}
        rows: list[dict[str, Any]] = []
        conversations: list[dict[str, Any]] = []
        for event, doc in items:
            extra = event
            record_id = doc.get("record_id") or ""
            if not record_id:
                logger.warning("Chat doc without record_id; skipping.")
                continue
            platform_id = doc.get("platform_id") or extra.get("platform_id") or "unknown"
            corpus_id = doc.get("corpus_id") or extra.get("corpus_id") or "unknown"
            venue_id = doc.get("venue_id") or extra.get("venue_id") or f"{platform_id}:{record_id}"
            channel = doc.get("channel") or ""
            sequence = doc.get("sequence")
            sent_at = doc.get("created_at")
            artefact_kind = doc.get("artefact_kind") or "chat"
            metadata_json = json.dumps(doc.get("metadata") or {}, default=str)
            author = doc.get("author_login")
            labels = doc.get("artefact_labels") or ["Artefact", "MessageArtefact"]
            vkey = (platform_id, corpus_id, venue_id)
            venues.setdefault(
                vkey,
                {
                    "platform_id": platform_id,
                    "corpus_id": corpus_id,
                    "venue_id": venue_id,
                    "external_id": venue_id,
                    "platform_name": extra.get("platform_name") or doc.get("platform_name"),
                    "platform_kind": extra.get("platform_kind") or doc.get("platform_kind"),
                    "corpus_name": extra.get("corpus_name") or doc.get("corpus_name"),
                },
            )
            if author:
                actor_types[author] = actor_types.get(author, platform_id)
            rows.append(
                {
                    "record_id": record_id,
                    "channel": channel,
                    "sequence": sequence,
                    "sent_at": sent_at,
                    "platform_id": platform_id,
                    "venue_id": venue_id,
                    "corpus_id": corpus_id,
                    "artefact_kind": artefact_kind,
                    "metadata_json": metadata_json,
                    "author": author,
                    "labels": self._final_labels(labels),
                }
            )
            if conversation_id := doc.get("conversation_id"):
                conversations.append(
                    {
                        "conversation_id": f"{corpus_id}:{conversation_id}",
                        "platform_id": platform_id,
                        "venue_id": venue_id,
                        "corpus_id": corpus_id,
                        "source_label": str(conversation_id),
                        "record_id": record_id,
                    }
                )
        await self._ensure_venues(venues)
        for login, atype in actor_types.items():
            await self.upsert_actor(login, actor_type=atype)
        if rows:
            await self._run(
                """
                UNWIND $rows AS x
                MERGE (m:ChatMessage {record_id: x.record_id})
                  ON CREATE SET m.channel = x.channel, m.sequence = x.sequence,
                                m.sent_at = x.sent_at, m.platform_id = x.platform_id,
                                m.venue_id = x.venue_id, m.corpus_id = x.corpus_id,
                                m.source_corpus = x.corpus_id,
                                m.artefact_kind = x.artefact_kind,
                                m.metadata_json = x.metadata_json
                  ON MATCH  SET m.channel = x.channel, m.sent_at = x.sent_at
                WITH m, x
                OPTIONAL MATCH (act:Actor {login: x.author})
                FOREACH(_ IN CASE WHEN act IS NOT NULL THEN [1] ELSE [] END |
                  MERGE (act)-[:AUTHORED]->(m)
                )
                WITH m, x
                MATCH (v:Venue {venue_id: x.venue_id})
                MERGE (v)-[:CONTAINS]->(m)
                WITH m, x
                SET m:$(x.labels)
                """,
                rows=rows,
            )
        if conversations:
            await self._run(
                """
            UNWIND $rows AS x
            MERGE (c:Conversation {conversation_id: x.conversation_id})
              ON CREATE SET c.platform_id = x.platform_id, c.venue_id = x.venue_id,
                            c.corpus_id = x.corpus_id, c.source_label = x.source_label
            WITH c, x
            MATCH (v:Venue {venue_id: x.venue_id})
            MERGE (v)-[:HAS_CONVERSATION]->(c)
            WITH c, x
            MATCH (m:ChatMessage {record_id: x.record_id})
            MERGE (c)-[:CONTAINS]->(m)
            """,
                rows=conversations,
            )

    async def _upsert_so_batch(self, items: list[tuple[dict[str, Any], dict[str, Any]]]) -> None:
        """Batch Stack Overflow post upsert + ANSWERS edges. Mirrors
        `_upsert_so_post`."""
        type_label = {
            "question": "StackOverflowQuestion",
            "answer": "StackOverflowAnswer",
            "comment": "StackOverflowComment",
        }
        actor_types: dict[str, str] = {}
        venues: dict[tuple[str, str, str], dict[str, Any]] = {}
        rows: list[dict[str, Any]] = []
        answers: list[dict[str, Any]] = []
        for event, doc in items:
            extra = event
            record_id = doc.get("record_id") or ""
            if not record_id:
                logger.warning("SO doc without record_id; skipping.")
                continue
            platform_id = doc.get("platform_id") or extra.get("platform_id") or "unknown"
            corpus_id = doc.get("corpus_id") or extra.get("corpus_id") or "unknown"
            venue_id = doc.get("venue_id") or extra.get("venue_id") or f"{platform_id}:{record_id}"
            post_type = doc.get("post_type") or "question"
            t_label = type_label.get(post_type, "StackOverflowPost")
            created_at = doc.get("created_at")
            metadata_json = json.dumps(doc.get("metadata") or {}, default=str)
            author = doc.get("author_login")
            vkey = (platform_id, corpus_id, venue_id)
            venues.setdefault(
                vkey,
                {
                    "platform_id": platform_id,
                    "corpus_id": corpus_id,
                    "venue_id": venue_id,
                    "external_id": venue_id,
                    "platform_name": extra.get("platform_name") or doc.get("platform_name"),
                    "platform_kind": extra.get("platform_kind") or doc.get("platform_kind"),
                    "corpus_name": extra.get("corpus_name") or doc.get("corpus_name"),
                },
            )
            if author:
                actor_types[author] = actor_types.get(author, platform_id)
            rows.append(
                {
                    "record_id": record_id,
                    "post_type": post_type,
                    "external_id": doc.get("external_id"),
                    "question_id": doc.get("question_id"),
                    "parent_post_id": doc.get("parent_post_id"),
                    "score": doc.get("score"),
                    "accepted": doc.get("accepted"),
                    "created_at": created_at,
                    "platform_id": platform_id,
                    "venue_id": venue_id,
                    "corpus_id": corpus_id,
                    "artefact_kind": f"so_{post_type}",
                    "metadata_json": metadata_json,
                    "author": author,
                    "labels": self._final_labels(
                        doc.get("artefact_labels") or ["Artefact", "PostArtefact", t_label]
                    ),
                }
            )
            if post_type == "answer" and (q := doc.get("question_record_id")):
                answers.append({"record_id": record_id, "q_record_id": q})
        await self._ensure_venues(venues)
        for login, atype in actor_types.items():
            await self.upsert_actor(login, actor_type=atype)
        if rows:
            await self._run(
                """
                UNWIND $rows AS x
                MERGE (p:StackOverflowPost {record_id: x.record_id})
                  ON CREATE SET p.post_type = x.post_type, p.external_id = x.external_id,
                                p.question_id = x.question_id,
                                p.parent_post_id = x.parent_post_id, p.score = x.score,
                                p.accepted = x.accepted, p.created_at = x.created_at,
                                p.platform_id = x.platform_id, p.venue_id = x.venue_id,
                                p.corpus_id = x.corpus_id, p.source_corpus = x.corpus_id,
                                p.artefact_kind = x.artefact_kind,
                                p.metadata_json = x.metadata_json
                  ON MATCH  SET p.post_type = x.post_type, p.created_at = x.created_at
                WITH p, x
                OPTIONAL MATCH (a:Actor {login: x.author})
                FOREACH(_ IN CASE WHEN a IS NOT NULL THEN [1] ELSE [] END |
                  MERGE (a)-[:AUTHORED]->(p)
                )
                WITH p, x
                MATCH (v:Venue {venue_id: x.venue_id})
                MERGE (v)-[:CONTAINS]->(p)
                WITH p, x
                SET p:$(x.labels)
                """,
                rows=rows,
            )
        if answers:
            await self._run(
                """
                UNWIND $rows AS x
                MATCH (a:StackOverflowPost {record_id: x.record_id})
                MERGE (q:StackOverflowPost {record_id: x.q_record_id})
                MERGE (a)-[:ANSWERS]->(q)
                """,
                rows=answers,
            )

    async def _upsert_github_issue_batch(
        self, items: list[tuple[dict[str, Any], dict[str, Any]]]
    ) -> None:
        """Batch GitHub Issue upsert. Mirrors `upsert_issue`."""
        actors: set[str] = set()
        repos: set[str] = set()
        venues: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        rows: list[dict[str, Any]] = []
        for event, doc in items:
            extra = event
            repo = event.get("repo_name", "")
            platform_id = extra.get("platform_id", "github")
            corpus_id = extra.get("corpus_id", "github")
            venue_id = extra.get("venue_id", f"github:{repo}")
            number = doc.get("number")
            if number is None:
                continue
            labels_list = [lbl.get("name", "") for lbl in doc.get("labels", [])]
            author = (doc.get("user") or {}).get("login", "")
            record_id = f"issue:{repo}:{number}"
            vkey = (platform_id, corpus_id, venue_id, repo)
            venues.setdefault(
                vkey,
                {
                    "platform_id": platform_id,
                    "corpus_id": corpus_id,
                    "venue_id": venue_id,
                    "external_id": repo,
                    "platform_name": extra.get("platform_name"),
                    "platform_kind": extra.get("platform_kind"),
                    "corpus_name": extra.get("corpus_name"),
                },
            )
            if repo:
                repos.add(repo)
            if author:
                actors.add(author)
            rows.append(
                {
                    "repo": repo,
                    "number": number,
                    "state": doc.get("state", ""),
                    "created_at": doc.get("created_at"),
                    "closed_at": doc.get("closed_at"),
                    "issue_labels": labels_list,
                    "author": author,
                    "record_id": record_id,
                    "platform_id": platform_id,
                    "venue_id": venue_id,
                    "corpus_id": corpus_id,
                    "labels": self._final_labels(
                        self._extra_labels(extra, ["Artefact", "IssueArtefact", "GitHubIssue"])
                    ),
                }
            )
        await self._ensure_venues(venues)
        for repo in repos:
            if repo not in self._seen_repos:
                await self._run("MERGE (r:Repository {full_name: $repo})", repo=repo)
                self._seen_repos.add(repo)
        for login in actors:
            await self.upsert_actor(login)
        if not rows:
            return
        await self._run(
            """
            UNWIND $rows AS x
            MERGE (r:Repository {full_name: x.repo})
            MERGE (i:Issue {repo: x.repo, number: x.number})
              ON CREATE SET i.state = x.state, i.created_at = x.created_at,
                            i.closed_at = x.closed_at, i.labels = x.issue_labels,
                            i.record_id = x.record_id, i.platform_id = x.platform_id,
                            i.venue_id = x.venue_id, i.corpus_id = x.corpus_id,
                            i.source_corpus = x.corpus_id, i.artefact_kind = 'issue'
              ON MATCH  SET i.state = x.state, i.closed_at = x.closed_at,
                            i.labels = x.issue_labels, i.record_id = x.record_id,
                            i.platform_id = x.platform_id, i.venue_id = x.venue_id,
                            i.corpus_id = x.corpus_id, i.source_corpus = x.corpus_id
            MERGE (r)-[:CONTAINS]->(i)
            WITH i, x
            OPTIONAL MATCH (a:Actor {login: x.author})
            FOREACH(_ IN CASE WHEN a IS NOT NULL THEN [1] ELSE [] END |
              MERGE (a)-[:AUTHORED]->(i)
            )
            WITH i, x
            MATCH (v:Venue {venue_id: x.venue_id})
            MERGE (v)-[:CONTAINS]->(i)
            WITH i, x
            SET i:$(x.labels)
            """,
            rows=rows,
        )

    async def _upsert_github_pr_batch(
        self, items: list[tuple[dict[str, Any], dict[str, Any]]]
    ) -> None:
        """Batch GitHub PullRequest upsert. Mirrors `upsert_pull_request`."""
        actors: set[str] = set()
        repos: set[str] = set()
        venues: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        rows: list[dict[str, Any]] = []
        for event, doc in items:
            extra = event
            repo = event.get("repo_name", "")
            platform_id = extra.get("platform_id", "github")
            corpus_id = extra.get("corpus_id", "github")
            venue_id = extra.get("venue_id", f"github:{repo}")
            number = doc.get("number")
            if number is None:
                continue
            author = (doc.get("user") or {}).get("login", "")
            record_id = f"pr:{repo}:{number}"
            vkey = (platform_id, corpus_id, venue_id, repo)
            venues.setdefault(
                vkey,
                {
                    "platform_id": platform_id,
                    "corpus_id": corpus_id,
                    "venue_id": venue_id,
                    "external_id": repo,
                    "platform_name": extra.get("platform_name"),
                    "platform_kind": extra.get("platform_kind"),
                    "corpus_name": extra.get("corpus_name"),
                },
            )
            if repo:
                repos.add(repo)
            if author:
                actors.add(author)
            rows.append(
                {
                    "repo": repo,
                    "number": number,
                    "state": doc.get("state", ""),
                    "merged": doc.get("merged", False),
                    "created_at": doc.get("created_at"),
                    "closed_at": doc.get("closed_at"),
                    "author": author,
                    "record_id": record_id,
                    "platform_id": platform_id,
                    "venue_id": venue_id,
                    "corpus_id": corpus_id,
                    "labels": self._final_labels(
                        self._extra_labels(
                            extra,
                            [
                                "Artefact",
                                "IssueArtefact",
                                "PullRequestArtefact",
                                "GitHubPullRequest",
                            ],
                        )
                    ),
                }
            )
        await self._ensure_venues(venues)
        for repo in repos:
            if repo not in self._seen_repos:
                await self._run("MERGE (r:Repository {full_name: $repo})", repo=repo)
                self._seen_repos.add(repo)
        for login in actors:
            await self.upsert_actor(login)
        if not rows:
            return
        await self._run(
            """
            UNWIND $rows AS x
            MERGE (r:Repository {full_name: x.repo})
            MERGE (p:PullRequest {repo: x.repo, number: x.number})
              ON CREATE SET p.state = x.state, p.merged = x.merged,
                            p.created_at = x.created_at, p.closed_at = x.closed_at,
                            p.record_id = x.record_id, p.platform_id = x.platform_id,
                            p.venue_id = x.venue_id, p.corpus_id = x.corpus_id,
                            p.source_corpus = x.corpus_id, p.artefact_kind = 'pull_request'
              ON MATCH  SET p.state = x.state, p.merged = x.merged,
                            p.closed_at = x.closed_at, p.record_id = x.record_id,
                            p.platform_id = x.platform_id, p.venue_id = x.venue_id,
                            p.corpus_id = x.corpus_id, p.source_corpus = x.corpus_id
            MERGE (r)-[:CONTAINS]->(p)
            WITH p, x
            OPTIONAL MATCH (a:Actor {login: x.author})
            FOREACH(_ IN CASE WHEN a IS NOT NULL THEN [1] ELSE [] END |
              MERGE (a)-[:AUTHORED]->(p)
            )
            WITH p, x
            MATCH (v:Venue {venue_id: x.venue_id})
            MERGE (v)-[:CONTAINS]->(p)
            WITH p, x
            SET p:$(x.labels)
            """,
            rows=rows,
        )

    async def _upsert_github_commit_batch(
        self, items: list[tuple[dict[str, Any], dict[str, Any]]]
    ) -> None:
        """Batch GitHub Commit upsert. Mirrors `upsert_commit`."""
        actors: set[str] = set()
        repos: set[str] = set()
        venues: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        rows: list[dict[str, Any]] = []
        for event, doc in items:
            extra = event
            repo = event.get("repo_name", "")
            platform_id = extra.get("platform_id", "github")
            corpus_id = extra.get("corpus_id", "github")
            venue_id = extra.get("venue_id", f"github:{repo}")
            sha = doc.get("sha", "")
            if not sha:
                continue
            commit_obj = doc.get("commit") or {}
            author_login = (doc.get("author") or {}).get("login", "")
            msg = commit_obj.get("message", "")
            summary = msg.splitlines()[0][:200] if msg else ""
            record_id = f"commit:{sha}"
            vkey = (platform_id, corpus_id, venue_id, repo)
            venues.setdefault(
                vkey,
                {
                    "platform_id": platform_id,
                    "corpus_id": corpus_id,
                    "venue_id": venue_id,
                    "external_id": repo,
                    "platform_name": extra.get("platform_name"),
                    "platform_kind": extra.get("platform_kind"),
                    "corpus_name": extra.get("corpus_name"),
                },
            )
            if repo:
                repos.add(repo)
            if author_login:
                actors.add(author_login)
            rows.append(
                {
                    "repo": repo,
                    "sha": sha,
                    "authored_at": (commit_obj.get("author") or {}).get("date"),
                    "committed_at": (commit_obj.get("committer") or {}).get("date"),
                    "summary": summary,
                    "author": author_login,
                    "record_id": record_id,
                    "platform_id": platform_id,
                    "venue_id": venue_id,
                    "corpus_id": corpus_id,
                    "labels": self._final_labels(
                        self._extra_labels(extra, ["Artefact", "CommitArtefact", "GitHubCommit"])
                    ),
                }
            )
        await self._ensure_venues(venues)
        for repo in repos:
            if repo not in self._seen_repos:
                await self._run("MERGE (r:Repository {full_name: $repo})", repo=repo)
                self._seen_repos.add(repo)
        for login in actors:
            await self.upsert_actor(login)
        if not rows:
            return
        await self._run(
            """
            UNWIND $rows AS x
            MERGE (r:Repository {full_name: x.repo})
            MERGE (c:Commit {sha: x.sha})
              ON CREATE SET c.authored_at = x.authored_at, c.committed_at = x.committed_at,
                            c.message_summary = x.summary, c.record_id = x.record_id,
                            c.platform_id = x.platform_id, c.venue_id = x.venue_id,
                            c.corpus_id = x.corpus_id, c.source_corpus = x.corpus_id,
                            c.artefact_kind = 'commit'
              ON MATCH  SET c.record_id = x.record_id, c.platform_id = x.platform_id,
                            c.venue_id = x.venue_id, c.corpus_id = x.corpus_id,
                            c.source_corpus = x.corpus_id
            MERGE (r)-[:CONTAINS]->(c)
            WITH c, x
            OPTIONAL MATCH (a:Actor {login: x.author})
            FOREACH(_ IN CASE WHEN a IS NOT NULL THEN [1] ELSE [] END |
              MERGE (a)-[:AUTHORED]->(c)
            )
            WITH c, x
            MATCH (v:Venue {venue_id: x.venue_id})
            MERGE (v)-[:CONTAINS]->(c)
            WITH c, x
            SET c:$(x.labels)
            """,
            rows=rows,
        )

    async def _ensure_venues(self, venues: dict[tuple[str, ...], dict[str, Any]]) -> None:
        """Memoized Platform/Venue/Corpus chain for a batch's unique venues."""
        for cfg in venues.values():
            await self._ensure_platform_venue_corpus(
                cfg["platform_id"],
                cfg["corpus_id"],
                cfg["venue_id"],
                cfg["external_id"],
                platform_name=cfg.get("platform_name"),
                platform_kind=cfg.get("platform_kind"),
                corpus_name=cfg.get("corpus_name"),
            )

    # ── SE-artefact layer ─────────────────────────────────────────────────────

    async def upsert_repository(self, repo: dict[str, Any]) -> None:
        """Cypher template: ontology.cypher §3.1"""
        await self._run(
            """
            MERGE (r:Repository {full_name: $full_name})
              ON CREATE SET r.created_at = $created_at,
                            r.language   = $language,
                            r.stars      = $stars,
                            r.mined_at   = $mined_at
              ON MATCH  SET r.stars      = $stars,
                            r.mined_at   = $mined_at
            """,
            full_name=repo.get("full_name", ""),
            created_at=repo.get("created_at"),
            language=repo.get("language"),
            stars=repo.get("stargazers_count", 0),
            mined_at=repo.get("_meta", {}).get("mined_at"),
        )

    async def upsert_actor(self, login: str, actor_type: str = "User") -> None:
        """Cypher template: ontology.cypher §3.2.
        Memoized in Phase 0: `ON CREATE SET` only, so first-write-wins and a
        repeat call with any actor_type writes nothing either way. Skipping is
        result-identical (Tier 3, CHANGELOG 2026-08-16)."""
        if login in self._seen_actors:
            return
        await self._run(
            """
            MERGE (a:Actor {login: $login})
              ON CREATE SET a.type = $type
            """,
            login=login,
            type=actor_type,
        )
        # memoise only after a successful write, so a failed write can retry
        self._seen_actors.add(login)

    # ── v0.8 multi-platform helpers ───────────────────────────────────────────

    async def _ensure_platform_venue_corpus(
        self,
        platform_id: str,
        corpus_id: str,
        venue_id: str,
        venue_external_id: str,
        *,
        platform_name: str | None = None,
        platform_kind: str | None = None,
        corpus_name: str | None = None,
    ) -> None:
        """
        Idempotent Platform / Venue / Corpus chain for one artefact's container.

        Corpus membership lives as a coarse (Corpus)-[:COVERS]->(Venue) edge plus
        the source_corpus property on every artefact — deliberately NOT a
        per-record edge (Alternative Jira alone is ~11.7M records). See
        FRAMEWORK_DESIGN.md §4.8 and AGENTS.md §5.6.

        Memoized in Phase 0 (Tier 3, CHANGELOG 2026-08-16): all SET values are
        deterministic given the three IDs, so after the first call per venue the
        write is a no-op and is skipped. Keep this a pure idempotent upsert.
        """
        key = (platform_id, corpus_id, venue_id)
        if key in self._seen_venues:
            return
        await self._run(
            """
            MERGE (p:Platform {platform_id: $platform_id})
              ON CREATE SET p.name = $platform_name, p.kind = $platform_kind
            MERGE (v:Venue {venue_id: $venue_id})
              ON CREATE SET v.platform_id = $platform_id, v.corpus_id = $corpus_id,
                            v.external_id = $venue_external_id
              ON MATCH  SET v.platform_id = $platform_id, v.corpus_id = $corpus_id,
                           v.external_id = $venue_external_id
            MERGE (p)-[:HAS_VENUE]->(v)
            MERGE (c:Corpus {corpus_id: $corpus_id})
              ON CREATE SET c.name = $corpus_name
            MERGE (c)-[:COVERS]->(v)
            """,
            platform_id=platform_id,
            platform_name=platform_name or platform_id,
            platform_kind=platform_kind or "unknown",
            corpus_id=corpus_id,
            corpus_name=corpus_name or corpus_id,
            venue_id=venue_id,
            venue_external_id=venue_external_id,
        )
        # memoise only after a successful write, so a failed write can retry
        self._seen_venues.add(key)

    @staticmethod
    def _extra_labels(extra: dict[str, Any], default: list[str]) -> list[str]:
        """Labels from the ingester's event if present, else the GitHub default."""
        return list(extra.get("artefact_labels") or default)

    @staticmethod
    def _final_labels(labels: list[str] | None) -> list[str]:
        """Artefact label list with the shared :Artefact layer guaranteed.
        Inlined into each per-artefact upsert so seeding stays a single
        round trip (Tier 3, CHANGELOG 2026-08-16)."""
        final = list(labels or [])
        if "Artefact" not in final:
            final.append("Artefact")
        return final

    async def upsert_issue(
        self,
        repo: str,
        doc: dict[str, Any],
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Upsert an Issue node + CONTAINS edge from Repository + AUTHORED edge.
        Cypher template: ontology.cypher §3.3.
        v0.8: also tags the node onto the multi-platform :Artefact layer.
        """
        extra = extra or {}
        platform_id = extra.get("platform_id", "github")
        corpus_id = extra.get("corpus_id", "github")
        venue_id = extra.get("venue_id", f"github:{repo}")
        labels: list[str] = self._extra_labels(extra, ["Artefact", "IssueArtefact", "GitHubIssue"])

        number = doc.get("number")
        labels_list = [lbl.get("name", "") for lbl in doc.get("labels", [])]
        author = (doc.get("user") or {}).get("login", "")
        record_id = f"issue:{repo}:{number}"

        await self._ensure_platform_venue_corpus(
            platform_id,
            corpus_id,
            venue_id,
            repo,
            platform_name=extra.get("platform_name"),
            platform_kind=extra.get("platform_kind"),
            corpus_name=extra.get("corpus_name"),
        )
        # Single-statement upsert (Tier 3, CHANGELOG 2026-08-16): node MERGE,
        # AUTHORED edge, venue CONTAINS edge, and dynamic labels all in one
        # transaction so an artefact is seeded atomically in one round trip.
        await self._run(
            """
            MERGE (r:Repository {full_name: $repo})
            MERGE (i:Issue {repo: $repo, number: $number})
              ON CREATE SET i.state = $state, i.created_at = $created_at,
                            i.closed_at = $closed_at, i.labels = $labels,
                            i.record_id = $record_id, i.platform_id = $platform_id,
                            i.venue_id = $venue_id, i.corpus_id = $corpus_id,
                            i.source_corpus = $corpus_id, i.artefact_kind = 'issue'
              ON MATCH  SET i.state = $state, i.closed_at = $closed_at,
                            i.labels = $labels, i.record_id = $record_id,
                            i.platform_id = $platform_id, i.venue_id = $venue_id,
                            i.corpus_id = $corpus_id, i.source_corpus = $corpus_id
            MERGE (r)-[:CONTAINS]->(i)
            WITH i
            MATCH (a:Actor {login: $author})
            MERGE (a)-[:AUTHORED]->(i)
            WITH i
            MATCH (v:Venue {venue_id: $venue_id})
            MERGE (v)-[:CONTAINS]->(i)
            WITH i
            SET i:$($artefact_labels)
            """,
            repo=repo,
            number=number,
            state=doc.get("state", ""),
            created_at=doc.get("created_at"),
            closed_at=doc.get("closed_at"),
            labels=labels_list,
            author=author,
            record_id=record_id,
            platform_id=platform_id,
            venue_id=venue_id,
            corpus_id=corpus_id,
            artefact_labels=self._final_labels(labels),
        )

    async def upsert_pull_request(
        self, repo: str, doc: dict[str, Any], extra: dict[str, Any] | None = None
    ) -> None:
        """Cypher template: ontology.cypher §3.4 (mirrors Issue template).
        v0.8: tags the node onto the multi-platform :Artefact layer."""
        extra = extra or {}
        platform_id = extra.get("platform_id", "github")
        corpus_id = extra.get("corpus_id", "github")
        venue_id = extra.get("venue_id", f"github:{repo}")
        labels: list[str] = self._extra_labels(
            extra, ["Artefact", "IssueArtefact", "PullRequestArtefact", "GitHubPullRequest"]
        )

        number = doc.get("number")
        author = (doc.get("user") or {}).get("login", "")
        record_id = f"pr:{repo}:{number}"

        await self._ensure_platform_venue_corpus(
            platform_id,
            corpus_id,
            venue_id,
            repo,
            platform_name=extra.get("platform_name"),
            platform_kind=extra.get("platform_kind"),
            corpus_name=extra.get("corpus_name"),
        )
        # Single-statement upsert (Tier 3, CHANGELOG 2026-08-16).
        await self._run(
            """
            MERGE (r:Repository {full_name: $repo})
            MERGE (p:PullRequest {repo: $repo, number: $number})
              ON CREATE SET p.state = $state, p.merged = $merged,
                            p.created_at = $created_at, p.closed_at = $closed_at,
                            p.record_id = $record_id, p.platform_id = $platform_id,
                            p.venue_id = $venue_id, p.corpus_id = $corpus_id,
                            p.source_corpus = $corpus_id, p.artefact_kind = 'pull_request'
              ON MATCH  SET p.state = $state, p.merged = $merged,
                            p.closed_at = $closed_at, p.record_id = $record_id,
                            p.platform_id = $platform_id, p.venue_id = $venue_id,
                            p.corpus_id = $corpus_id, p.source_corpus = $corpus_id
            MERGE (r)-[:CONTAINS]->(p)
            WITH p
            MATCH (a:Actor {login: $author})
            MERGE (a)-[:AUTHORED]->(p)
            WITH p
            MATCH (v:Venue {venue_id: $venue_id})
            MERGE (v)-[:CONTAINS]->(p)
            WITH p
            SET p:$($artefact_labels)
            """,
            repo=repo,
            number=number,
            state=doc.get("state", ""),
            merged=doc.get("merged", False),
            created_at=doc.get("created_at"),
            closed_at=doc.get("closed_at"),
            author=author,
            record_id=record_id,
            platform_id=platform_id,
            venue_id=venue_id,
            corpus_id=corpus_id,
            artefact_labels=self._final_labels(labels),
        )

    async def upsert_commit(
        self, repo: str, doc: dict[str, Any], extra: dict[str, Any] | None = None
    ) -> None:
        extra = extra or {}
        platform_id = extra.get("platform_id", "github")
        corpus_id = extra.get("corpus_id", "github")
        venue_id = extra.get("venue_id", f"github:{repo}")
        labels: list[str] = self._extra_labels(
            extra, ["Artefact", "CommitArtefact", "GitHubCommit"]
        )

        sha = doc.get("sha", "")
        commit_obj = doc.get("commit") or {}
        author_login = (doc.get("author") or {}).get("login", "")
        msg = commit_obj.get("message", "")
        summary = msg.splitlines()[0][:200] if msg else ""
        record_id = f"commit:{sha}"

        await self._ensure_platform_venue_corpus(
            platform_id,
            corpus_id,
            venue_id,
            repo,
            platform_name=extra.get("platform_name"),
            platform_kind=extra.get("platform_kind"),
            corpus_name=extra.get("corpus_name"),
        )
        # Single-statement upsert (Tier 3, CHANGELOG 2026-08-16).
        await self._run(
            """
            MERGE (r:Repository {full_name: $repo})
            MERGE (c:Commit {sha: $sha})
              ON CREATE SET c.authored_at    = $authored_at,
                            c.committed_at   = $committed_at,
                            c.message_summary = $summary,
                            c.record_id = $record_id, c.platform_id = $platform_id,
                            c.venue_id = $venue_id, c.corpus_id = $corpus_id,
                            c.source_corpus = $corpus_id, c.artefact_kind = 'commit'
              ON MATCH  SET c.record_id = $record_id, c.platform_id = $platform_id,
                            c.venue_id = $venue_id, c.corpus_id = $corpus_id,
                            c.source_corpus = $corpus_id
            MERGE (r)-[:CONTAINS]->(c)
            WITH c
            OPTIONAL MATCH (a:Actor {login: $author})
            FOREACH(_ IN CASE WHEN a IS NOT NULL THEN [1] ELSE [] END |
              MERGE (a)-[:AUTHORED]->(c)
            )
            WITH c
            MATCH (v:Venue {venue_id: $venue_id})
            MERGE (v)-[:CONTAINS]->(c)
            WITH c
            SET c:$($artefact_labels)
            """,
            repo=repo,
            sha=sha,
            authored_at=(commit_obj.get("author") or {}).get("date"),
            committed_at=(commit_obj.get("committer") or {}).get("date"),
            summary=summary,
            author=author_login,
            record_id=record_id,
            platform_id=platform_id,
            venue_id=venue_id,
            corpus_id=corpus_id,
            artefact_labels=self._final_labels(labels),
        )

    async def upsert_text_unit(self, unit_event: dict[str, Any]) -> None:
        """
        MERGE a TextUnit node and wire HAS_TEXT edge to its parent.
        Cypher template: ontology.cypher §3.7.
        Parent lookup uses the parent_id convention from BUILD_SPEC.md §4.2.
        """
        tu_id = unit_event["text_unit_id"]
        parent_id = unit_event["parent_id"]
        parent_type = unit_event["parent_type"]
        repo = unit_event["repo"]
        number = unit_event.get("parent_number")
        role = unit_event["role"]

        # Build the MATCH clause dynamically based on parent_type
        if parent_type in ("issue",):
            parent_match = "MATCH (parent:Issue {repo: $repo, number: $number})"
        elif parent_type == "pull_request":
            parent_match = "MATCH (parent:PullRequest {repo: $repo, number: $number})"
        elif parent_type == "commit":
            parent_match = "MATCH (parent:Commit {sha: $sha})"
        elif parent_type == "email":
            parent_match = "MATCH (parent:EmailMessage {urn: $urn})"
        elif parent_type in ("jira_issue", "bugzilla_issue", "chat_message", "so_post"):
            # v0.8 external artefacts are matched by their globally namespaced
            # record_id (= parent_id) — never by string-splitting the parent_id.
            parent_match = "MATCH (parent:Artefact {record_id: $parent_record_id})"
        else:
            logger.warning("Unknown parent_type '%s' for TextUnit %s", parent_type, tu_id)
            return

        sha = parent_id.split(":")[-1] if parent_type == "commit" else None
        # parent_id convention for emails: "email:<urn>" (urn contains ':').
        urn = parent_id.split(":", 1)[1] if parent_type == "email" else None

        await self._run(
            f"""
            {parent_match}
            MERGE (u:TextUnit {{id: $tu_id}})
              ON CREATE SET u.text = $text, u.lang = $lang,
                            u.token_count = $token_count, u.sha256 = $sha256,
                            u.created_at = $created_at, u.position = $position,
                            u.role = $role, u.parent_type = $parent_type,
                            u.author_login = $author_login
              ON MATCH  SET u.role = $role, u.parent_type = $parent_type,
                            u.author_login = $author_login
            MERGE (parent)-[:HAS_TEXT {{role: $role}}]->(u)
            """,
            tu_id=tu_id,
            text=unit_event.get("text", ""),
            lang=unit_event.get("lang"),
            token_count=unit_event.get("token_count", 0),
            sha256=unit_event.get("sha256", ""),
            created_at=unit_event.get("created_at"),
            position=unit_event.get("position", 0),
            role=role,
            parent_type=parent_type,
            author_login=unit_event.get("author_login"),
            repo=repo,
            number=number,
            sha=sha,
            urn=urn,
            parent_record_id=parent_id,
        )

    async def upsert_text_units_batch(self, unit_events: list[dict[str, Any]]) -> None:
        """
        Batch MERGE of TextUnit nodes + HAS_TEXT edges in ONE UNWIND statement.

        The Phase-1 hot path (CHANGELOG 2026-08-16): the per-unit loop cost one
        Neo4j round trip per TextUnit, capping Phase 1 at ~500 units/s while the
        extractor produced ~8,000/s — so stream_units buffered the corpus in
        Redis until the Docker VM OOM'd. One UNWIND of 100 units ≈ one round
        trip, lifting Phase 1 past the extractor's rate so the queue never grows.

        Parents are matched uniformly via `:Artefact {record_id: u.parent_id}`:
        every Phase-0-seeded parent (Issue/PR/Commit/EmailMessage/chat/SO/Jira)
        carries the :Artefact label and its record_id == parent_id, and that
        lookup uses the artefact_record_id index. `upsert_text_unit` (type-
        specific MATCH) is kept as the per-unit fallback.
        """
        if not unit_events:
            return
        # Actors are memoized (near-zero cost after warmup); only unique logins.
        for login in {u.get("author_login") for u in unit_events if u.get("author_login")}:
            await self.upsert_actor(login)
        await self._run(
            """
            UNWIND $units AS u
            MATCH (parent:Artefact {record_id: u.parent_id})
            MERGE (tu:TextUnit {id: u.text_unit_id})
              ON CREATE SET tu.text = u.text, tu.lang = u.lang,
                            tu.token_count = u.token_count, tu.sha256 = u.sha256,
                            tu.created_at = u.created_at, tu.position = u.position,
                            tu.role = u.role, tu.parent_type = u.parent_type,
                            tu.author_login = u.author_login
              ON MATCH  SET tu.role = u.role, tu.parent_type = u.parent_type,
                            tu.author_login = u.author_login
            MERGE (parent)-[:HAS_TEXT {role: u.role}]->(tu)
            """,
            units=[
                {
                    "text_unit_id": u["text_unit_id"],
                    "parent_id": u["parent_id"],
                    "role": u["role"],
                    "text": u.get("text", ""),
                    "lang": u.get("lang"),
                    "token_count": u.get("token_count", 0),
                    "sha256": u.get("sha256", ""),
                    "created_at": u.get("created_at"),
                    "position": u.get("position", 0),
                    "parent_type": u.get("parent_type"),
                    "author_login": u.get("author_login"),
                }
                for u in unit_events
            ],
        )

    # ── v0.8 external artefact families ──────────────────────────────────────

    async def _upsert_external_artefact(
        self,
        item_type: str,
        repo: str,
        doc: dict[str, Any],
        extra: dict[str, Any],
    ) -> None:
        """
        Seed a first-class node for Jira issues, Bugzilla issues, chat/IRC
        messages, and Stack Overflow posts. The node's natural key is the
        namespaced record_id (= TextUnit parent_id); platform/venue/corpus
        tagging is delegated to the family-specific methods below.
        """
        record_id = doc.get("record_id") or ""
        if not record_id:
            logger.warning("External %s doc without record_id; skipping.", item_type)
            return
        platform_id = doc.get("platform_id") or extra.get("platform_id") or "unknown"
        corpus_id = doc.get("corpus_id") or extra.get("corpus_id") or "unknown"
        venue_id = doc.get("venue_id") or extra.get("venue_id") or f"{platform_id}:{repo}"
        author_login = doc.get("author_login")

        await self._ensure_platform_venue_corpus(
            platform_id,
            corpus_id,
            venue_id,
            venue_id,
            platform_name=extra.get("platform_name") or doc.get("platform_name"),
            platform_kind=extra.get("platform_kind") or doc.get("platform_kind"),
            corpus_name=extra.get("corpus_name") or doc.get("corpus_name"),
        )
        if author_login:
            # External actors carry a namespaced login (external_common.namespaced_login);
            # their platform is the actor_type. See FRAMEWORK_DESIGN.md §4.8.
            await self.upsert_actor(author_login, actor_type=platform_id)

        if item_type in ("jira_issue", "bugzilla_issue"):
            label = "JiraIssue" if item_type == "jira_issue" else "BugzillaIssue"
            await self._upsert_issue_artefact(
                label, item_type, record_id, doc, venue_id, platform_id, corpus_id
            )
        elif item_type == "chat_message":
            await self._upsert_chat_artefact(record_id, doc, venue_id, platform_id, corpus_id)
        elif item_type == "so_post":
            await self._upsert_so_post(record_id, doc, venue_id, platform_id, corpus_id)

    async def _upsert_issue_artefact(
        self,
        node_label: str,
        artefact_kind: str,
        record_id: str,
        doc: dict[str, Any],
        venue_id: str,
        platform_id: str,
        corpus_id: str,
    ) -> None:
        """Shared Jira/Bugzilla node upsert (issue-like external artefacts)."""
        created_at = doc.get("created_at") or doc.get("created")
        state = doc.get("state") or doc.get("status") or ""
        external_id = doc.get("external_id") or record_id
        metadata_json = json.dumps(doc.get("metadata") or {}, default=str)
        author = doc.get("author_login")

        # Single-statement upsert (Tier 3, CHANGELOG 2026-08-16). The AUTHORED
        # edge is OPTIONAL so authorless docs do not fail the whole statement
        # (matches the previous guarded call).
        await self._run(
            f"""
            MERGE (a:{node_label} {{record_id: $record_id}})
              ON CREATE SET a.platform_id = $platform_id, a.venue_id = $venue_id,
                            a.corpus_id = $corpus_id, a.source_corpus = $corpus_id,
                            a.artefact_kind = $artefact_kind, a.created_at = $created_at,
                            a.external_id = $external_id, a.state = $state,
                            a.metadata_json = $metadata_json
              ON MATCH  SET a.created_at = $created_at, a.state = $state,
                            a.external_id = $external_id
            WITH a
            OPTIONAL MATCH (act:Actor {{login: $author}})
            FOREACH(_ IN CASE WHEN act IS NOT NULL THEN [1] ELSE [] END |
              MERGE (act)-[:AUTHORED]->(a)
            )
            WITH a
            MATCH (v:Venue {{venue_id: $venue_id}})
            MERGE (v)-[:CONTAINS]->(a)
            WITH a
            SET a:$($artefact_labels)
            """,
            record_id=record_id,
            platform_id=platform_id,
            venue_id=venue_id,
            corpus_id=corpus_id,
            artefact_kind=artefact_kind,
            created_at=created_at,
            external_id=external_id,
            state=state,
            metadata_json=metadata_json,
            author=author,
            artefact_labels=self._final_labels(
                doc.get("artefact_labels") or ["Artefact", "IssueArtefact"]
            ),
        )

    async def _upsert_chat_artefact(
        self,
        record_id: str,
        doc: dict[str, Any],
        venue_id: str,
        platform_id: str,
        corpus_id: str,
    ) -> None:
        """Slack/Discord/Gitter/IRC message node + optional Conversation wiring."""
        channel = doc.get("channel") or ""
        sequence = doc.get("sequence")
        sent_at = doc.get("created_at")
        artefact_kind = doc.get("artefact_kind") or "chat"
        metadata_json = json.dumps(doc.get("metadata") or {}, default=str)
        labels = doc.get("artefact_labels") or ["Artefact", "MessageArtefact"]
        author = doc.get("author_login")

        # Single-statement upsert (Tier 3, CHANGELOG 2026-08-16); conversation
        # wiring stays a separate conditional call below.
        await self._run(
            """
            MERGE (m:ChatMessage {record_id: $record_id})
              ON CREATE SET m.channel = $channel, m.sequence = $sequence,
                            m.sent_at = $sent_at, m.platform_id = $platform_id,
                            m.venue_id = $venue_id, m.corpus_id = $corpus_id,
                            m.source_corpus = $corpus_id, m.artefact_kind = $artefact_kind,
                            m.metadata_json = $metadata_json
              ON MATCH  SET m.channel = $channel, m.sent_at = $sent_at
            WITH m
            OPTIONAL MATCH (act:Actor {login: $author})
            FOREACH(_ IN CASE WHEN act IS NOT NULL THEN [1] ELSE [] END |
              MERGE (act)-[:AUTHORED]->(m)
            )
            WITH m
            MATCH (v:Venue {venue_id: $venue_id})
            MERGE (v)-[:CONTAINS]->(m)
            WITH m
            SET m:$($artefact_labels)
            """,
            record_id=record_id,
            channel=channel,
            sequence=sequence,
            sent_at=sent_at,
            platform_id=platform_id,
            venue_id=venue_id,
            corpus_id=corpus_id,
            artefact_kind=artefact_kind,
            metadata_json=metadata_json,
            author=author,
            artefact_labels=self._final_labels(labels),
        )
        # Conversation wiring: dataset-provided/inferred grouping label. The
        # conversation_id is part of the node key so each corpus's grouping is
        # kept separate (a Slack '1' must not merge with an IRC 'T1').
        if conversation_id := doc.get("conversation_id"):
            conversation_record = f"{corpus_id}:{conversation_id}"
            await self._run(
                """
                MERGE (c:Conversation {conversation_id: $conversation_id})
                  ON CREATE SET c.platform_id = $platform_id, c.venue_id = $venue_id,
                                c.corpus_id = $corpus_id, c.source_label = $source_label
                WITH c
                MATCH (v:Venue {venue_id: $venue_id})
                MERGE (v)-[:HAS_CONVERSATION]->(c)
                WITH c
                MATCH (m:ChatMessage {record_id: $record_id})
                MERGE (c)-[:CONTAINS]->(m)
                """,
                conversation_id=conversation_record,
                platform_id=platform_id,
                venue_id=venue_id,
                corpus_id=corpus_id,
                source_label=str(doc.get("conversation_id")),
                record_id=record_id,
            )

    async def _upsert_so_post(
        self,
        record_id: str,
        doc: dict[str, Any],
        venue_id: str,
        platform_id: str,
        corpus_id: str,
    ) -> None:
        """Stack Overflow question/answer/comment node (emotion workbook)."""
        post_type = doc.get("post_type") or "question"
        type_label = {
            "question": "StackOverflowQuestion",
            "answer": "StackOverflowAnswer",
            "comment": "StackOverflowComment",
        }.get(post_type, "StackOverflowPost")
        created_at = doc.get("created_at")
        metadata_json = json.dumps(doc.get("metadata") or {}, default=str)
        author = doc.get("author_login")

        # Single-statement upsert (Tier 3, CHANGELOG 2026-08-16); the ANSWERS
        # edge for answers stays a separate conditional call below.
        await self._run(
            """
            MERGE (p:StackOverflowPost {record_id: $record_id})
              ON CREATE SET p.post_type = $post_type, p.external_id = $external_id,
                            p.question_id = $question_id, p.parent_post_id = $parent_post_id,
                            p.score = $score, p.accepted = $accepted,
                            p.created_at = $created_at, p.platform_id = $platform_id,
                            p.venue_id = $venue_id, p.corpus_id = $corpus_id,
                            p.source_corpus = $corpus_id, p.artefact_kind = $artefact_kind,
                            p.metadata_json = $metadata_json
              ON MATCH  SET p.post_type = $post_type, p.created_at = $created_at
            WITH p
            OPTIONAL MATCH (act:Actor {login: $author})
            FOREACH(_ IN CASE WHEN act IS NOT NULL THEN [1] ELSE [] END |
              MERGE (act)-[:AUTHORED]->(p)
            )
            WITH p
            MATCH (v:Venue {venue_id: $venue_id})
            MERGE (v)-[:CONTAINS]->(p)
            WITH p
            SET p:$($artefact_labels)
            """,
            record_id=record_id,
            post_type=post_type,
            external_id=doc.get("external_id"),
            question_id=doc.get("question_id"),
            parent_post_id=doc.get("parent_post_id"),
            score=doc.get("score"),
            accepted=doc.get("accepted"),
            created_at=created_at,
            platform_id=platform_id,
            venue_id=venue_id,
            corpus_id=corpus_id,
            artefact_kind=f"so_{post_type}",
            metadata_json=metadata_json,
            author=author,
            artefact_labels=self._final_labels(
                doc.get("artefact_labels") or ["Artefact", "PostArtefact", type_label]
            ),
        )
        if post_type == "answer" and (q_record_id := doc.get("question_record_id")):
            await self._run(
                """
                MATCH (a:StackOverflowPost {record_id: $record_id})
                MERGE (q:StackOverflowPost {record_id: $q_record_id})
                MERGE (a)-[:ANSWERS]->(q)
                """,
                record_id=record_id,
                q_record_id=q_record_id,
            )

    # ── Mailing-list layer (Webis Gmane) — v0.6 ───────────────────────────────

    async def upsert_email_message(
        self, doc: dict[str, Any], extra: dict[str, Any] | None = None
    ) -> None:
        """
        Seed MailingList, Actor, and EmailMessage nodes from a raw Gmane doc.
        Cypher template: ontology.cypher §3.13.

        Threading headers (in_reply_to, references) are stored as node
        properties; REPLIES_TO edges are created later by the enrichment pass
        (enrichment/email_threading.py) once both ends exist — same pattern as
        GitHub REFERENCES edges. The `from` value is anonymized by Webis; we
        store it verbatim as the Actor login. Cross-platform identity
        resolution (email actor ↔ GitHub actor) is explicitly out of scope.

        v0.8: also tags the node onto the :Artefact:MessageArtefact layer.
        `extra` may carry corpus_id/venue_id for the curated email corpora;
        Gmane/OCEAN default to their own corpus/venue derived from `group`.
        """
        extra = extra or {}
        urn = doc.get("urn") or ""
        if not urn:
            logger.warning("Email doc without urn; skipping.")
            return
        headers = doc.get("headers") or {}
        group = doc.get("group") or ""
        sender = (headers.get("from") or "").strip()
        message_id, in_reply_to, references = _sanitize_email_threading(
            headers.get("message_id"),
            headers.get("in_reply_to"),
            headers.get("references"),
        )

        corpus_id = extra.get("corpus_id") or (
            doc.get("_meta", {}).get("corpus_id")
            or (
                "ocean"
                if str(urn).startswith("ocean:")
                else ("gmane" if str(urn).startswith("gmane:") else "email")
            )
        )
        venue_platform = extra.get("platform_id", "mailing_list")
        venue_id = extra.get("venue_id") or f"{venue_platform}:{group or corpus_id}"
        platform_id = extra.get("platform_id", "mailing_list")

        venue_platform = extra.get("platform_id", "mailing_list")
        venue_id = extra.get("venue_id") or f"{venue_platform}:{group or corpus_id}"
        platform_id = extra.get("platform_id", "mailing_list")

        # Actor is memoized (Tier 3, CHANGELOG 2026-08-16); the MailingList node
        # and CONTAINS edge are folded into the single-statement upsert below.
        if sender:
            await self.upsert_actor(sender)

        await self._ensure_platform_venue_corpus(
            platform_id,
            corpus_id,
            venue_id,
            group or corpus_id,
            platform_name=extra.get("platform_name"),
            platform_kind="email",
            corpus_name=extra.get("corpus_name"),
        )
        # Single-statement upsert (Tier 3, CHANGELOG 2026-08-16): node MERGE,
        # MailingList CONTAINS (conditional), AUTHORED (optional), venue
        # CONTAINS, and labels all in one transaction.
        await self._run(
            """
            MERGE (e:EmailMessage {urn: $urn})
              ON CREATE SET e.message_id = $message_id,
                            e.subject = $subject,
                            e.date = $date,
                            e.group = $group,
                            e.list_id = $list_id,
                            e.in_reply_to = $in_reply_to,
                            e.references = $references,
                            e.lang = $lang,
                            e.record_id = $record_id,
                            e.platform_id = $platform_id,
                            e.venue_id = $venue_id,
                            e.corpus_id = $corpus_id,
                            e.source_corpus = $corpus_id,
                            e.artefact_kind = 'email'
              ON MATCH  SET e.record_id = $record_id,
                            e.platform_id = $platform_id,
                            e.venue_id = $venue_id,
                            e.corpus_id = $corpus_id,
                            e.source_corpus = $corpus_id,
                            e.message_id = $message_id,
                            e.in_reply_to = $in_reply_to,
                            e.references = $references
            WITH e
            FOREACH(_ IN CASE WHEN $group IS NOT NULL AND $group <> '' THEN [1] ELSE [] END |
              MERGE (m:MailingList {name: $group})
              MERGE (m)-[:CONTAINS]->(e)
            )
            WITH e
            OPTIONAL MATCH (a:Actor {login: $sender})
            FOREACH(_ IN CASE WHEN a IS NOT NULL THEN [1] ELSE [] END |
              MERGE (a)-[:AUTHORED]->(e)
            )
            WITH e
            MATCH (v:Venue {venue_id: $venue_id})
            MERGE (v)-[:CONTAINS]->(e)
            WITH e
            SET e:$($artefact_labels)
            """,
            urn=urn,
            message_id=message_id,
            subject=headers.get("subject"),
            date=headers.get("date"),
            group=group,
            list_id=headers.get("list_id"),
            in_reply_to=in_reply_to,
            references=references,
            lang=doc.get("lang"),
            record_id=f"email:{urn}",
            platform_id=platform_id,
            venue_id=venue_id,
            corpus_id=corpus_id,
            sender=sender,
            artefact_labels=self._final_labels(
                extra.get("artefact_labels") or ["Artefact", "MessageArtefact"]
            ),
        )

    # ── NK-analytical layer ───────────────────────────────────────────────────

    async def upsert_signals_batch(self, signals: list[dict[str, Any]]) -> None:
        """
        Batch MERGE of Signal nodes + HAS_SIGNAL edges.
        Cypher template: ontology.cypher §3.8.
        Verdict signals (payload.__verdict__) are routed to ClassifierVerdict
        nodes; lexical/rhetorical signals wire MATCHES_MARKER / INSTANTIATES.

        All three post-steps are batched UNWIND statements (CHANGELOG
        2026-08-18): the previous implementation called one helper method per
        signal, i.e. one Neo4j round trip per signal — ~3M round trips for the
        corpus. Each step now costs one round trip per ~100 signals.
        """
        verdict_signals = [s for s in signals if s.get("payload", {}).get("__verdict__")]
        plain_signals = [s for s in signals if not s.get("payload", {}).get("__verdict__")]

        if not plain_signals and verdict_signals:
            # Only verdict events in this batch (no plain signals to write).
            # Write the verdict directly; it is still the completion marker
            # written last among whatever this batch has (CHANGELOG 2026-08-27).
            return await self._upsert_verdicts(verdict_signals)

        if not plain_signals:
            return

        await self._run(
            """
            UNWIND $signals AS s
            MATCH (u:TextUnit {id: s.text_unit_id})
            MERGE (sig:Signal {id: s.signal_id})
              ON CREATE SET sig.layer        = s.layer,
                            sig.category     = s.category,
                            sig.subcategory  = s.subcategory,
                            sig.surface_form = s.surface_form,
                            sig.span_start   = s.span_start,
                            sig.span_end     = s.span_end,
                            sig.rule_id      = s.rule_id,
                            sig.rule_version = s.rule_version,
                            sig.confidence   = s.confidence,
                            sig.weight       = s.weight,
                            sig.status       = s.status,
                            sig.payload_json = s.payload_json,
                            sig.created_at   = datetime()
              ON MATCH  SET sig.weight       = s.weight,
                            sig.status       = s.status
            MERGE (u)-[:HAS_SIGNAL]->(sig)
            """,
            signals=[
                {
                    "signal_id": s.get("signal_id"),
                    "text_unit_id": s.get("text_unit_id"),
                    "layer": s.get("layer"),
                    "category": s.get("category"),
                    "subcategory": s.get("subcategory"),
                    "surface_form": s.get("surface_form", ""),
                    "span_start": s.get("span_start", 0),
                    "span_end": s.get("span_end", 0),
                    "rule_id": s.get("rule_id"),
                    "rule_version": s.get("rule_version"),
                    "confidence": s.get("confidence"),
                    # v0.2 (MARKER_REVIEW.md §3.5): analysis-time confidence hint
                    # and lifecycle label. ON MATCH SET above means a later
                    # re-run with an updated rule weight/status (e.g. empirical
                    # calibration promoting candidate -> active) refreshes
                    # existing Signal nodes rather than requiring a rebuild.
                    "weight": s.get("weight"),
                    "status": s.get("status", "active"),
                    # Neo4j cannot store a nested Map as a property — serialise to JSON.
                    # Strip internal sentinel keys (prefixed with __) before serialising.
                    # Parse in analysis with apoc.convert.fromJsonMap(sig.payload_json).
                    "payload_json": json.dumps(
                        {
                            k: v
                            for k, v in (s.get("payload") or {}).items()
                            if not k.startswith("__")
                        },
                        default=str,
                    ),
                }
                for s in plain_signals
            ],
        )

        # Post-batch wiring in ONE round trip per signal family (not one per
        # signal): MATCHES_MARKER and INSTANTIATES edges.
        lexical = [s for s in plain_signals if s.get("layer") == "lexical"]
        rhetorical = [s for s in plain_signals if s.get("layer") == "rhetorical"]

        if lexical:
            await self._run(
                """
                UNWIND $rows AS s
                MATCH (sig:Signal {id: s.signal_id})
                MERGE (m:LexicalMarker {lemma: s.lemma, lexicon_version: s.lv})
                  ON CREATE SET m.pos = s.pos, m.category = s.category,
                                m.subcategory = s.subcategory, m.polarity = s.polarity,
                                m.source_citation = s.source
                MERGE (sig)-[:MATCHES_MARKER]->(m)
                """,
                rows=[
                    {
                        "signal_id": s.get("signal_id"),
                        "lemma": (s.get("payload") or {}).get("lemma", ""),
                        "lv": (s.get("payload") or {}).get("lexicon_version", ""),
                        "pos": (s.get("payload") or {}).get("pos", ""),
                        "category": s.get("category", ""),
                        "subcategory": s.get("subcategory"),
                        "polarity": (s.get("payload") or {}).get("polarity", "neutral"),
                        "source": (s.get("payload") or {}).get("source_citation", ""),
                    }
                    for s in lexical
                ],
            )
        if rhetorical:
            await self._run(
                """
                UNWIND $rows AS s
                MATCH (sig:Signal {id: s.signal_id})
                MERGE (f:RhetoricalFigure {figure_id: s.figure_id})
                  ON CREATE SET f.family = s.family, f.subtype = s.subtype,
                                f.description = s.description,
                                f.source_citation = s.source
                MERGE (sig)-[:INSTANTIATES]->(f)
                """,
                rows=[
                    {
                        "signal_id": s.get("signal_id"),
                        "figure_id": (s.get("payload") or {}).get("figure_id", ""),
                        "family": (s.get("payload") or {}).get("family", ""),
                        "subtype": (s.get("payload") or {}).get("subtype", ""),
                        "description": (s.get("payload") or {}).get("description", ""),
                        "source": (s.get("payload") or {}).get("source_citation", ""),
                    }
                    for s in rhetorical
                ],
            )

        # Completion marker is written LAST (CHANGELOG 2026-08-27). A unit is
        # only considered annotated (CLASSIFIED_AS present) once all of its
        # plain signals + wiring have been committed; if any of those earlier
        # transactions failed, no verdict is written and the unit is re-selected
        # by --only-unannotated. MERGEs are idempotent, so a partially-written
        # unit is safely re-done.
        if verdict_signals:
            await self._upsert_verdicts(verdict_signals)

    async def _upsert_verdicts(self, verdict_signals: list[dict[str, Any]]) -> None:
        """MERGE ClassifierVerdict nodes + CLASSIFIED_AS edges (run LAST)."""
        await self._run(
            """
            UNWIND $rows AS v
            MATCH (u:TextUnit {id: v.text_unit_id})
            MERGE (cv:ClassifierVerdict {
              text_unit_id:  v.text_unit_id,
              model_id:      v.model_id,
              model_version: v.model_version
            })
              ON CREATE SET cv.label = v.label, cv.confidence = v.confidence,
                            cv.predicted_at = datetime()
              ON MATCH  SET cv.label = v.label, cv.confidence = v.confidence,
                            cv.predicted_at = datetime()
            MERGE (u)-[:CLASSIFIED_AS]->(cv)
            """,
            rows=[
                {
                    "text_unit_id": s.get("text_unit_id"),
                    "model_id": (s.get("payload") or {}).get("model_id", ""),
                    "model_version": (s.get("payload") or {}).get("model_version", ""),
                    "label": (s.get("payload") or {}).get("label", -1),
                    "confidence": s.get("confidence"),
                }
                for s in verdict_signals
            ],
        )

    # ── internal helper ───────────────────────────────────────────────────────

    async def _run(self, cypher: str, **params: Any) -> None:
        """Execute a single Cypher statement in its own transaction."""
        async with self._driver.session() as session:
            await session.run(cypher, **params)
