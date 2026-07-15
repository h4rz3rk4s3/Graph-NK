"""
Central configuration for GraphRAG-NK.

All values are read from environment variables or a .env file.
Copy .env.example → .env and fill in secrets before running.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── GitHub ────────────────────────────────────────────────────────────────
    github_token: str = Field(..., alias="GITHUB_TOKEN")

    # ── MongoDB ───────────────────────────────────────────────────────────────
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "graph_nk_mongodb"

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
    neo4j_password: str = "none" #"researchpw"
    apply_schema_on_startup: bool = True

    # ── Miner ─────────────────────────────────────────────────────────────────
    rate_limit_margin: int = 10
    concurrent_requests: int = 5
    max_retries: int = 5

# ── Classifier ────────────────────────────────────────────────────────────
    classifier_model_path: str = "models/roberta-non-knowledge-v8-base"
    # "mps" for Apple Silicon, "cuda" for NVIDIA, "cpu" as fallback
    classifier_device: str = "mps"
    classifier_batch_size: int = 64

    # ── Annotator worker ──────────────────────────────────────────────────────
    # How many units to batch before flushing signals to the projector
    annotator_batch_size: int = 64       # units per spaCy.pipe + classifier batch
    spacy_model: str = "en_core_web_lg"  # sm: no vectors, faster; lg also works
    spacy_n_process: int = 1             # >1 → multi-process spaCy.pipe (more CPU)

    # ── Annotation scope (what to annotate) ───────────────────────────────────
    # These narrow the set of TextUnits the annotator processes. lang/min-tokens
    # work on existing data; role/parent-type/bot/referenced-PR filters require
    # a stage-1 re-run to backfill the fields on TextUnit nodes (idempotent).
    annotate_languages: list[str] = ["en"]   # only these langs; [] = all
    annotate_min_tokens: int = 2              # skip units shorter than this
    annotate_roles: list[str] = []            # e.g. ["body","comment_body"]; [] = all
    annotate_parent_types: list[str] = []     # e.g. ["issue","pull_request","email"]; [] = all
    annotate_skip_bots: bool = True           # skip *[bot] authors (templated text)
    annotate_only_referenced_prs: bool = False  # PR units only if PR <-> Issue ref

    # ── Mailing lists (Webis Gmane Email Corpus 2019) — v0.6 ──────────────────
    # Which corpus segment classes become TextUnits. `quotation` MUST stay
    # excluded by default: quoted text repeats the previous author's words, so
    # NK signals in quotes would be duplicated across every reply of a thread
    # and attributed to the wrong author. Signatures / patches / logs / code are
    # not authored epistemic discourse. See CHANGELOG 2026-06-04 (v0.6).
    email_segment_labels: list[str] = ["paragraph", "section_heading"]


    # Gmane ingester tuning (see CHANGELOG — ingestion throughput rework).
    # How many (urn, doc) pairs to accumulate before one bulk Mongo write.
    gmane_batch_size: int = 2000
    # How many parsed docs to accumulate before one pipelined Redis XADD burst.
    gmane_redis_batch_size: int = 2000
    # Number of worker processes for --parallel-files. 0 = os.cpu_count().
    gmane_num_workers: int = 0


    # ── Annotation pattern/lexicon version (v0.2 — MARKER_REVIEW.md) ─────────
    # Each annotator resolves its pattern/lexicon path as
    # patterns/<name>_v<pattern_set_version>.yml (or lexicons/... for the
    # lexicon). Defaults to "0.2". Set to "0.1" to run the pre-review
    # baseline for comparison — this is the versioning MARKER_REVIEW.md
    # refers to when it says corrections "preserve provenance": both file
    # sets stay on disk, and this setting picks which one loads.
    # NOTE: v0.2 morpho_syntactic patterns use spaCy DependencyMatcher, which
    # requires the parser (see annotators.base.make_nlp) — reverting to "0.1"
    # does not re-disable the parser automatically; do that explicitly if the
    # speed matters and no DependencyMatcher rule is in play.
    pattern_set_version: str = "0.2"


settings = Settings()
