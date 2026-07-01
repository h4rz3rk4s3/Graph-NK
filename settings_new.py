"""
Central configuration for GraphRAG-NK.

All values are read from environment variables or a .env file.
Copy .env.example → .env and fill in secrets before running.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── GitHub ────────────────────────────────────────────────────────────────
    github_token: str = ""

    # ── MongoDB ───────────────────────────────────────────────────────────────
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "graphrag_nk"

    # Connection pool / resilience (see storage.make_mongo_client).
    # Bounded so large backlogs don't open hundreds of connections at once.
    mongo_max_pool_size: int = 50
    mongo_server_selection_timeout_ms: int = 30000
    mongo_socket_timeout_ms: int = 120000

    # Max concurrent Mongo fetches per worker. Keep modest so the driver's
    # background server-monitor coroutine is never starved (this is what
    # caused "connection pool paused" on large backlogs).
    mongo_fetch_concurrency: int = 16

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # Redis stream names — shared across all workers
    stream_raw: str = "graphrag.raw"
    stream_units: str = "graphrag.units"
    stream_signals: str = "graphrag.signals"

    # ── Neo4j ─────────────────────────────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "researchpw"

    # Apply the (idempotent) constraints + indexes on projector startup, so the
    # schema is always present regardless of how Neo4j was launched. Prevents the
    # missing-index full-scan slowdown in Phase 1.
    apply_schema_on_startup: bool = True

    # ── Miner ─────────────────────────────────────────────────────────────────
    rate_limit_margin: int = 10
    concurrent_requests: int = 5
    max_retries: int = 5

    # ── Classifier ────────────────────────────────────────────────────────────
    classifier_model_path: str = "./models/nk_roberta"
    # "mps" for Apple Silicon, "cuda" for NVIDIA, "cpu" as fallback
    classifier_device: str = "mps"
    classifier_batch_size: int = 64  # larger batch → better MPS throughput

    # ── Annotation batching / spaCy (v0.5 speed) ──────────────────────────────
    # One shared spaCy pipeline parses each TextUnit once; rule annotators run on
    # the shared Doc. Texts are parsed in batches via nlp.pipe.
    annotator_batch_size: int = 64       # units per spaCy.pipe + classifier batch
    spacy_model: str = "en_core_web_sm"  # sm: no vectors, faster; lg also works
    spacy_n_process: int = 1             # >1 → multi-process spaCy.pipe (more CPU)

    # ── Annotation scope (what to annotate) ───────────────────────────────────
    # These narrow the set of TextUnits the annotator processes. lang/min-tokens
    # work on existing data; role/parent-type/bot/referenced-PR filters require
    # a stage-1 re-run to backfill the fields on TextUnit nodes (idempotent).
    annotate_languages: list[str] = ["en"]   # only these langs; [] = all
    annotate_min_tokens: int = 2              # skip units shorter than this
    annotate_roles: list[str] = []            # e.g. ["body","comment_body"]; [] = all
    annotate_parent_types: list[str] = []     # e.g. ["issue","pull_request"]; [] = all
    annotate_skip_bots: bool = True           # skip *[bot] authors (templated text)
    annotate_only_referenced_prs: bool = False  # PR units only if PR <-> Issue ref


settings = Settings()
