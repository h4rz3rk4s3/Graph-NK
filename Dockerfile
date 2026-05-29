# ─────────────────────────────────────────────────────────────────────────────
# GraphRAG-NK — Single image used by ALL workers and the miner.
# Every service in docker-compose.yml is built from this one file.
# Different services just override CMD.
#
# Build manually (from the project root, same dir as this file):
#   docker build -t graphrag-nk .
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.13

# ── System deps ───────────────────────────────────────────────────────────────
# build-essential + cmake  : llama-cpp-python wheel compilation
# libgomp1                 : OpenMP runtime for torch / sentence-transformers
# curl                     : healthchecks and model downloads
# git                      : some HuggingFace repos need it internally
# RUN apt-get update && apt-get install -y --no-install-recommends \
#         curl \
#         libgomp1 \
#     && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python deps (separate layer — only rebuilt when requirements change) ──────
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ── Application source ────────────────────────────────────────────────────────
COPY . .

# ── Runtime ───────────────────────────────────────────────────────────────────
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Default — overridden per-service in docker-compose.yml
CMD ["python", "main.py", "all"]
