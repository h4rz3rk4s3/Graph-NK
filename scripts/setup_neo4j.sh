#!/usr/bin/env bash
# scripts/setup_neo4j.sh
#
# Applies the GraphRAG-NK ontology DDL (constraints + indexes) to a running Neo4j
# instance using cypher-shell.
#
# Usage:
#   bash scripts/setup_neo4j.sh
#
# Prerequisites:
#   - Neo4j running (e.g. via docker compose up -d neo4j)
#   - cypher-shell on PATH, OR we fall back to docker exec.
#   - NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD set (or defaults below).
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

NEO4J_URI="${NEO4J_URI:-bolt://localhost:7687}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-researchpw}"
ONTOLOGY_FILE="$(dirname "$0")/../ontology/ontology.cypher"

echo ">>> Applying ontology: $ONTOLOGY_FILE"
echo ">>> Target: $NEO4J_URI"

# Strip comment lines and blank lines from the ontology file,
# then split on semicolons and execute each statement individually.
# cypher-shell on Neo4j 5 accepts one statement at a time via stdin.

python3 - <<'PYEOF'
import subprocess, sys, pathlib, os, re, time

ontology = pathlib.Path(os.environ.get("ONTOLOGY_FILE", "ontology/ontology.cypher"))
uri  = os.environ.get("NEO4J_URI",      "bolt://localhost:7687")
user = os.environ.get("NEO4J_USER",     "neo4j")
pw   = os.environ.get("NEO4J_PASSWORD", "researchpw")

raw = ontology.read_text(encoding="utf-8")

# Remove full-line comments (// ...) and blank lines
lines = [l for l in raw.splitlines() if not l.strip().startswith("//") and l.strip()]
text  = "\n".join(lines)

# Split on semicolons that end a statement
statements = [s.strip() for s in re.split(r";\s*\n", text) if s.strip()]

ok = err = 0
for stmt in statements:
    if not stmt or stmt.startswith("//"):
        continue
    result = subprocess.run(
        ["cypher-shell", "-u", user, "-p", pw, "--address", uri, stmt + ";"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        ok += 1
    else:
        # Many CREATE CONSTRAINT IF NOT EXISTS warnings are benign
        if "already exists" in result.stderr or "EquivalentSchemaRuleAlreadyExists" in result.stderr:
            ok += 1
        else:
            print(f"[WARN] {result.stderr.strip()[:200]}", file=sys.stderr)
            err += 1

print(f"Ontology applied: {ok} OK, {err} errors.")
if err:
    sys.exit(1)
PYEOF

echo ">>> Done."
