"""
Email threading enrichment (v0.6) — creates REPLIES_TO edges.

The projector stores each email's `in_reply_to` header as a node property.
This pass connects (reply)-[:REPLIES_TO]->(parent) wherever the parent's
message_id is present in the graph — the email-native counterpart of GitHub's
REFERENCES enrichment, run after ingestion for the same reason: both endpoints
must exist before edges can be drawn.

Runs as a single batched Cypher statement per call; relies on the
email_message_id and email_in_reply_to indexes from ontology.cypher.

Notes:
- message_id is not unique in crawled archives; if several EmailMessage nodes
  share one message_id, each becomes a REPLIES_TO target (faithful to the data;
  disambiguation is an analysis-time concern).
- Replies whose parent is outside the ingested scope simply get no edge —
  detectable later via: e.in_reply_to IS NOT NULL AND NOT (e)-[:REPLIES_TO]->().
"""
from __future__ import annotations

import logging

from neo4j import AsyncGraphDatabase

from settings import settings

logger = logging.getLogger("enrichment.email_threading")


async def run_email_threading_enrichment() -> None:
    """Create REPLIES_TO edges for all emails whose parent is in the graph."""
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    try:
        async with driver.session() as session:
            result = await session.run(
                """
                MATCH (reply:EmailMessage)
                WHERE reply.in_reply_to IS NOT NULL AND reply.in_reply_to <> ''
                MATCH (parent:EmailMessage {message_id: reply.in_reply_to})
                WHERE parent <> reply
                MERGE (reply)-[:REPLIES_TO]->(parent)
                RETURN count(*) AS edges
                """
            )
            rec = await result.single()
            edges = rec["edges"] if rec else 0

            result = await session.run(
                """
                MATCH (e:EmailMessage)
                WHERE e.in_reply_to IS NOT NULL AND e.in_reply_to <> ''
                  AND NOT (e)-[:REPLIES_TO]->()
                RETURN count(e) AS dangling
                """
            )
            rec = await result.single()
            dangling = rec["dangling"] if rec else 0

        logger.info(
            "Email threading: %d REPLIES_TO edges ensured; %d replies whose "
            "parent is outside the ingested scope (no edge).",
            edges, dangling,
        )
    finally:
        await driver.close()
