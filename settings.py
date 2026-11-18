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
    # >= projector_phase0_concurrency so Phase 0's concurrent find_one calls
    # are not capped by the pool (Tier 3, CHANGELOG 2026-08-16).
    mongo_max_pool_size: int = 128
    mongo_server_selection_timeout_ms: int = 30000
    mongo_socket_timeout_ms: int = 120000

    # Max concurrent Mongo fetches per worker. Keep modest so the driver's
    # background server-monitor coroutine is never starved (this is what
    # caused "connection pool paused" on large backlogs).
    mongo_fetch_concurrency: int = 16
    # Phase-0 concurrency (Tier 3, CHANGELOG 2026-08-16): Phase 0 runs alone in
    # its own sub-stage and drives the Mongo find_one + Neo4j upsert path, so it
    # is the throughput knob for artefact seeding. Must be <= mongo_max_pool_size.
    projector_phase0_concurrency: int = 64
    # Phase-0 read batch size (CHANGELOG 2026-08-19): events read from stream_raw
    # per Redis XREAD, then fetched from Mongo in ONE $in find per collection and
    # written to Neo4j as per-family UNWIND statements — so the batch amortizes
    # all three round-trip hops instead of doing them per event.
    phase0_batch_size: int = 1000

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # Redis stream names — shared across all workers
    stream_raw: str = "graphrag.raw"
    stream_units: str = "graphrag.units"
    stream_signals: str = "graphrag.signals"

    # ── Neo4j ─────────────────────────────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "none"  # "researchpw"
    apply_schema_on_startup: bool = True

    # ── Miner ─────────────────────────────────────────────────────────────────
    rate_limit_margin: int = 10
    concurrent_requests: int = 5
    max_retries: int = 5

    # ── Classifier ────────────────────────────────────────────────────────────
    classifier_model_path: str = "models/roberta-non-knowledge-v8-base"
    # "mps" for Apple Silicon, "cuda" for NVIDIA, "cpu" as fallback
    classifier_device: str = "mps"
    # Classifier microbatch size. The annotator sorts each 64-unit parse batch
    # by text length and splits it into these smaller tokenizer calls so a long
    # Jira body does not pad every short neighbour to 512 tokens.
    classifier_batch_size: int = 16

    # ── Annotator worker ──────────────────────────────────────────────────────
    # How many units to batch before flushing signals to the projector
    annotator_batch_size: int = 64  # units per spaCy.pipe + classifier batch
    spacy_model: str = "en_core_web_md"  # sm: no vectors, faster; lg also works
    spacy_n_process: int = 1  # >1 → multi-process spaCy.pipe (more CPU)
    # Ceiling on the stream_signals backlog before the annotator pauses
    # (CHANGELOG 2026-08-21, Milestone D). The Stage-2 projector drains this
    # stream concurrently; a producer that outraces the drain would otherwise
    # drive Redis into its 12 GiB noeviction OOM wall. 0 disables the gate.
    annotator_max_stream_signals_backlog: int = 200_000

    # Annotator resume (CHANGELOG 2026-08-23): the id-ordered walk makes the
    # last fully-published unit id a resume watermark. Stored per (id_lo, id_hi)
    # shard range under this Redis key prefix; a restart with --resume continues
    # from the high-water mark instead of re-annotating from the start of the
    # range. The classifier emits a verdict for every parsed unit, which is what
    # makes a post-hoc frontier recoverable even without a stored mark.
    annotate_hwm_key_prefix: str = "graphrag.annotate.hwm"

    # ── Annotation scope (what to annotate) ───────────────────────────────────
    # These narrow the set of TextUnits the annotator processes. lang/min-tokens
    # work on existing data; role/parent-type/bot/referenced-PR filters require
    # a stage-1 re-run to backfill the fields on TextUnit nodes (idempotent).
    annotate_languages: list[str] = ["en"]  # only these languages; [] = all
    annotate_min_tokens: int = 2  # skip tokens shorter than this
    annotate_roles: list[str] = []  # e.g. ["body","comment_body"]; [] = all
    annotate_parent_types: list[str] = []  # e.g. ["issue","pull_request","email"]; [] = all
    annotate_skip_bots: bool = True  # skip *[bot] authors (templated text)
    annotate_only_referenced_prs: bool = False  # PR units only if PR <-> Issue ref
    # Skip TextUnits longer than this many characters. spaCy's parser caps input
    # at nlp.max_length (1M default) — a pasted log/stack trace can exceed that
    # and raise [E088], killing the whole annotator run. A >100k-char unit is a
    # paste, not epistemic discourse, so it is skipped at annotation time (a
    # scope decision like annotate_min_tokens — NOT signal filtering; see
    # CHANGELOG 2026-08-20). Live census: 2,745 Jira body/comment units exceed
    # 100k, max 15.1M chars; that is the source of the 2026-08-20 crash.
    annotate_max_chars: int = 100000

    # ── Extractor backpressure (Fix 2, CHANGELOG 2026-08-16) ─────────────────
    # Hard ceiling on the stream_units backlog. If Phase 1 ever falls behind
    # (it now batches, so this is a safety net), the extractor pauses instead of
    # letting Redis buffer the corpus — the OOM trigger on the 2026-08-16 run.
    extractor_max_stream_units_backlog: int = 50000

    # ── Projector Phase-2 batching (CHANGELOG 2026-08-23) ───────────────────
    # Signals are flushed to Neo4j in batches (one UNWIND per family). Larger
    # batches amortize the round trip across more writes; with an adequate page
    # cache (the 2026-08-21 smoke drained ~9.6k/s) the batch size is the next
    # knob. Raised from the old module constant 100 to 500.
    projector_signal_batch_size: int = 500

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

    # ── Curated MSR datasets (v0.8) ─────────────────────────────────────────
    # Root of the curated MSR corpora on the external drive. Ingesters default
    # under this root and accept explicit --path overrides. No hardcoded drive
    # paths inside parsers (FRAMEWORK_DESIGN.md §12).
    # TODO: Move to env, before pushing to GitHub
    datasets_root: str = "/Volumes/Samsung SSD 990 PRO 4TB/Graph_NK_datasets"
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
