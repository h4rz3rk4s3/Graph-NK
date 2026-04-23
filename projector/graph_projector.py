"""
Module 4 — GraphProjector.

The ONLY module allowed to write Cypher. All annotators emit plain Signal dicts;
this module decides how they become nodes and edges in Neo4j.

Cypher templates mirror ontology/ontology.cypher §3 exactly.
Any ontology change requires updating both files — see AGENTS.md §3.6.

See FRAMEWORK_DESIGN.md §5 Module 4; BUILD_SPEC.md §6 M3.
"""
from __future__ import annotations

import logging
from typing import Any

from neo4j import AsyncGraphDatabase, AsyncDriver

from settings import settings

logger = logging.getLogger(__name__)


class GraphProjector:
    """Wraps all Cypher writes for the GraphRAG-NK ontology."""

    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    @classmethod
    async def create(cls) -> "GraphProjector":
        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        return cls(driver)

    async def close(self) -> None:
        await self._driver.close()

    # ── Phase 0 entry point ───────────────────────────────────────────────────

    async def upsert_artefact_from_raw(
        self, item_type: str, item_subtype: str, repo: str, doc: dict[str, Any]
    ) -> None:
        """
        Seed Repository / Actor / Issue / PullRequest / Commit nodes from a raw
        MongoDB document. Called during Phase 0 of the projector worker, before
        TextUnit nodes are written, so that MATCH clauses in upsert_text_unit
        always find an existing parent node.

        Fix for CHANGELOG.md ⚠️ limitation 1.
        """
        # Seed the Actor for the artefact author
        author_obj = doc.get("user") or {}
        if login := author_obj.get("login"):
            await self.upsert_actor(login)

        # Guarantee the Repository node exists (cheap idempotent MERGE)
        if repo:
            await self._run("MERGE (r:Repository {full_name: $repo})", repo=repo)

        if item_type == "repository":
            await self.upsert_repository(doc)
        elif item_subtype == "issue":
            await self.upsert_issue(repo, doc)
        elif item_subtype == "pull_request":
            await self.upsert_pull_request(repo, doc)
        elif item_type == "commit":
            await self.upsert_commit(repo, doc)

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
            full_name  = repo.get("full_name", ""),
            created_at = repo.get("created_at"),
            language   = repo.get("language"),
            stars      = repo.get("stargazers_count", 0),
            mined_at   = repo.get("_meta", {}).get("mined_at"),
        )

    async def upsert_actor(self, login: str, actor_type: str = "User") -> None:
        """Cypher template: ontology.cypher §3.2"""
        await self._run(
            """
            MERGE (a:Actor {login: $login})
              ON CREATE SET a.type = $type
            """,
            login=login, type=actor_type,
        )

    async def upsert_issue(self, repo: str, doc: dict[str, Any]) -> None:
        """Upsert an Issue node + CONTAINS edge from Repository + AUTHORED edge.
        Cypher template: ontology.cypher §3.3"""
        number = doc.get("number")
        labels_list = [lbl.get("name", "") for lbl in doc.get("labels", [])]
        author = (doc.get("user") or {}).get("login", "")

        await self._run(
            """
            MERGE (r:Repository {full_name: $repo})
            MERGE (i:Issue {repo: $repo, number: $number})
              ON CREATE SET i.state = $state, i.created_at = $created_at,
                            i.closed_at = $closed_at, i.labels = $labels
              ON MATCH  SET i.state = $state, i.closed_at = $closed_at,
                            i.labels = $labels
            MERGE (r)-[:CONTAINS]->(i)
            WITH i
            MATCH (a:Actor {login: $author})
            MERGE (a)-[:AUTHORED]->(i)
            """,
            repo=repo, number=number,
            state=doc.get("state", ""),
            created_at=doc.get("created_at"),
            closed_at=doc.get("closed_at"),
            labels=labels_list,
            author=author,
        )

    async def upsert_pull_request(self, repo: str, doc: dict[str, Any]) -> None:
        """Cypher template: ontology.cypher §3.4 (mirrors Issue template)."""
        number = doc.get("number")
        author = (doc.get("user") or {}).get("login", "")

        await self._run(
            """
            MERGE (r:Repository {full_name: $repo})
            MERGE (p:PullRequest {repo: $repo, number: $number})
              ON CREATE SET p.state = $state, p.merged = $merged,
                            p.created_at = $created_at, p.closed_at = $closed_at
              ON MATCH  SET p.state = $state, p.merged = $merged,
                            p.closed_at = $closed_at
            MERGE (r)-[:CONTAINS]->(p)
            WITH p
            MATCH (a:Actor {login: $author})
            MERGE (a)-[:AUTHORED]->(p)
            """,
            repo=repo, number=number,
            state=doc.get("state", ""),
            merged=doc.get("merged", False),
            created_at=doc.get("created_at"),
            closed_at=doc.get("closed_at"),
            author=author,
        )

    async def upsert_commit(self, repo: str, doc: dict[str, Any]) -> None:
        sha = doc.get("sha", "")
        commit_obj = doc.get("commit") or {}
        author_login = (doc.get("author") or {}).get("login", "")
        msg = commit_obj.get("message", "")
        summary = msg.splitlines()[0][:200] if msg else ""

        await self._run(
            """
            MERGE (r:Repository {full_name: $repo})
            MERGE (c:Commit {sha: $sha})
              ON CREATE SET c.authored_at    = $authored_at,
                            c.committed_at   = $committed_at,
                            c.message_summary = $summary
            MERGE (r)-[:CONTAINS]->(c)
            WITH c
            OPTIONAL MATCH (a:Actor {login: $author})
            FOREACH(_ IN CASE WHEN a IS NOT NULL THEN [1] ELSE [] END |
              MERGE (a)-[:AUTHORED]->(c)
            )
            """,
            repo=repo, sha=sha,
            authored_at  = (commit_obj.get("author")    or {}).get("date"),
            committed_at = (commit_obj.get("committer") or {}).get("date"),
            summary=summary,
            author=author_login,
        )

    async def upsert_text_unit(self, unit_event: dict[str, Any]) -> None:
        """
        MERGE a TextUnit node and wire HAS_TEXT edge to its parent.
        Cypher template: ontology.cypher §3.7.
        Parent lookup uses the parent_id convention from BUILD_SPEC.md §4.2.
        """
        tu_id       = unit_event["text_unit_id"]
        parent_id   = unit_event["parent_id"]
        parent_type = unit_event["parent_type"]
        repo        = unit_event["repo"]
        number      = unit_event.get("parent_number")
        role        = unit_event["role"]

        # Build the MATCH clause dynamically based on parent_type
        if parent_type in ("issue",):
            parent_match = "MATCH (parent:Issue {repo: $repo, number: $number})"
        elif parent_type == "pull_request":
            parent_match = "MATCH (parent:PullRequest {repo: $repo, number: $number})"
        elif parent_type == "commit":
            parent_match = "MATCH (parent:Commit {sha: $sha})"
        else:
            logger.warning("Unknown parent_type '%s' for TextUnit %s", parent_type, tu_id)
            return

        sha = parent_id.split(":")[-1] if parent_type == "commit" else None

        await self._run(
            f"""
            {parent_match}
            MERGE (u:TextUnit {{id: $tu_id}})
              ON CREATE SET u.text = $text, u.lang = $lang,
                            u.token_count = $token_count, u.sha256 = $sha256,
                            u.created_at = $created_at, u.position = $position
            MERGE (parent)-[:HAS_TEXT {{role: $role}}]->(u)
            """,
            tu_id      = tu_id,
            text       = unit_event.get("text", ""),
            lang       = unit_event.get("lang"),
            token_count= unit_event.get("token_count", 0),
            sha256     = unit_event.get("sha256", ""),
            created_at = unit_event.get("created_at"),
            position   = unit_event.get("position", 0),
            role       = role,
            repo       = repo,
            number     = number,
            sha        = sha,
        )

    # ── NK-analytical layer ───────────────────────────────────────────────────

    async def upsert_signals_batch(self, signals: list[dict[str, Any]]) -> None:
        """
        Batch MERGE of Signal nodes + HAS_SIGNAL edges.
        Cypher template: ontology.cypher §3.8.
        Verdict signals (payload.__verdict__) are routed to upsert_classifier_verdict.
        Rhetorical signals trigger upsert_rhetorical_figure.
        Lexical signals trigger upsert_lexical_marker.
        """
        plain_signals = []
        for s in signals:
            if s.get("payload", {}).get("__verdict__"):
                await self.upsert_classifier_verdict(s)
            else:
                plain_signals.append(s)

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
                            sig.payload      = s.payload,
                            sig.created_at   = datetime()
            MERGE (u)-[:HAS_SIGNAL]->(sig)
            """,
            signals=[{
                "signal_id":    s.get("signal_id"),
                "text_unit_id": s.get("text_unit_id"),
                "layer":        s.get("layer"),
                "category":     s.get("category"),
                "subcategory":  s.get("subcategory"),
                "surface_form": s.get("surface_form", ""),
                "span_start":   s.get("span_start", 0),
                "span_end":     s.get("span_end", 0),
                "rule_id":      s.get("rule_id"),
                "rule_version": s.get("rule_version"),
                "confidence":   s.get("confidence"),
                "payload":      {k: v for k, v in (s.get("payload") or {}).items()
                                 if not k.startswith("__")},
            } for s in plain_signals],
        )

        # Post-batch: wire MATCHES_MARKER and INSTANTIATES edges
        for s in plain_signals:
            if s.get("layer") == "lexical":
                await self._upsert_lexical_marker(s)
            elif s.get("layer") == "rhetorical":
                await self._upsert_rhetorical_figure(s)

    async def upsert_classifier_verdict(self, signal: dict[str, Any]) -> None:
        """
        MERGE a ClassifierVerdict node.
        Cypher template: ontology.cypher §3.11.
        """
        p = signal.get("payload", {})
        await self._run(
            """
            MATCH (u:TextUnit {id: $text_unit_id})
            MERGE (v:ClassifierVerdict {
              text_unit_id:  $text_unit_id,
              model_id:      $model_id,
              model_version: $model_version
            })
              ON CREATE SET v.label = $label, v.confidence = $confidence,
                            v.predicted_at = datetime()
              ON MATCH  SET v.label = $label, v.confidence = $confidence,
                            v.predicted_at = datetime()
            MERGE (u)-[:CLASSIFIED_AS]->(v)
            """,
            text_unit_id  = signal.get("text_unit_id"),
            model_id      = p.get("model_id", ""),
            model_version = p.get("model_version", ""),
            label         = p.get("label", -1),
            confidence    = signal.get("confidence"),
        )

    async def _upsert_lexical_marker(self, signal: dict[str, Any]) -> None:
        """Link Signal → LexicalMarker. Cypher template: ontology.cypher §3.9."""
        p = signal.get("payload", {})
        await self._run(
            """
            MATCH (sig:Signal {id: $signal_id})
            MERGE (m:LexicalMarker {lemma: $lemma, lexicon_version: $lv})
              ON CREATE SET m.pos = $pos, m.category = $category,
                            m.subcategory = $subcategory, m.polarity = $polarity,
                            m.source_citation = $source
            MERGE (sig)-[:MATCHES_MARKER]->(m)
            """,
            signal_id = signal.get("signal_id"),
            lemma     = p.get("lemma", ""),
            lv        = p.get("lexicon_version", ""),
            pos       = p.get("pos", ""),
            category  = signal.get("category", ""),
            subcategory = signal.get("subcategory"),
            polarity  = p.get("polarity", "neutral"),
            source    = p.get("source_citation", ""),
        )

    async def _upsert_rhetorical_figure(self, signal: dict[str, Any]) -> None:
        """Link Signal → RhetoricalFigure. Cypher template: ontology.cypher §3.10."""
        p = signal.get("payload", {})
        await self._run(
            """
            MATCH (sig:Signal {id: $signal_id})
            MERGE (f:RhetoricalFigure {figure_id: $figure_id})
              ON CREATE SET f.family = $family, f.subtype = $subtype,
                            f.description = $description,
                            f.source_citation = $source
            MERGE (sig)-[:INSTANTIATES]->(f)
            """,
            signal_id   = signal.get("signal_id"),
            figure_id   = p.get("figure_id", ""),
            family      = p.get("family", ""),
            subtype     = p.get("subtype", ""),
            description = p.get("description", ""),
            source      = p.get("source_citation", ""),
        )

    # ── internal helper ───────────────────────────────────────────────────────

    async def _run(self, cypher: str, **params: Any) -> None:
        """Execute a single Cypher statement in its own transaction."""
        async with self._driver.session() as session:
            await session.run(cypher, **params)
