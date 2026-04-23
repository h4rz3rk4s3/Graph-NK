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

    # ── Miner ─────────────────────────────────────────────────────────────────
    rate_limit_margin: int = 10
    concurrent_requests: int = 5
    max_retries: int = 5

    # ── Classifier ────────────────────────────────────────────────────────────
    classifier_model_path: str = "./models/nk_roberta"
    # "mps" for Apple Silicon, "cuda" for NVIDIA, "cpu" as fallback
    classifier_device: str = "mps"
    classifier_batch_size: int = 16

    # ── Annotator worker ──────────────────────────────────────────────────────
    # How many units to batch before flushing signals to the projector
    annotator_batch_size: int = 32

    # ── spaCy ─────────────────────────────────────────────────────────────────
    spacy_model: str = "en_core_web_lg"


settings = Settings()
