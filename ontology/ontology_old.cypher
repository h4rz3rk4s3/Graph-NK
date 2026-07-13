// ============================================================================
// GraphRAG-NK — Ontology DDL & MERGE templates
// ----------------------------------------------------------------------------
// Mirrors ontology/schema.yml and §4 of FRAMEWORK_DESIGN.md.
// Apply with: cypher-shell < ontology.cypher
// Safe to re-run (all statements idempotent).
// ============================================================================

// ─────────────────────────────────────────────────────────────────────────────
// 1. CONSTRAINTS (natural keys)
// ─────────────────────────────────────────────────────────────────────────────

// SE-artefact layer
CREATE CONSTRAINT repository_full_name IF NOT EXISTS
  FOR (r:Repository) REQUIRE r.full_name IS UNIQUE;

CREATE CONSTRAINT actor_login IF NOT EXISTS
  FOR (a:Actor) REQUIRE a.login IS UNIQUE;

CREATE CONSTRAINT issue_key IF NOT EXISTS
  FOR (i:Issue) REQUIRE (i.repo, i.number) IS UNIQUE;

CREATE CONSTRAINT pr_key IF NOT EXISTS
  FOR (p:PullRequest) REQUIRE (p.repo, p.number) IS UNIQUE;

CREATE CONSTRAINT commit_sha IF NOT EXISTS
  FOR (c:Commit) REQUIRE c.sha IS UNIQUE;

CREATE CONSTRAINT comment_id IF NOT EXISTS
  FOR (c:Comment) REQUIRE c.github_comment_id IS UNIQUE;

CREATE CONSTRAINT textunit_id IF NOT EXISTS
  FOR (t:TextUnit) REQUIRE t.id IS UNIQUE;
// t.id is constructed as "{parent_id}:{position}" in the projector.

// NK-analytical layer
CREATE CONSTRAINT signal_id IF NOT EXISTS
  FOR (s:Signal) REQUIRE s.id IS UNIQUE;
// s.id is constructed as "{text_unit_id}:{rule_id}:{span_start}".

CREATE CONSTRAINT lexicalmarker_key IF NOT EXISTS
  FOR (m:LexicalMarker) REQUIRE (m.lemma, m.lexicon_version) IS UNIQUE;

CREATE CONSTRAINT rhetoricalfigure_id IF NOT EXISTS
  FOR (f:RhetoricalFigure) REQUIRE f.figure_id IS UNIQUE;

CREATE CONSTRAINT verdict_key IF NOT EXISTS
  FOR (v:ClassifierVerdict) REQUIRE (v.text_unit_id, v.model_id, v.model_version) IS UNIQUE;

CREATE CONSTRAINT ignorancetype_id IF NOT EXISTS
  FOR (t:IgnoranceType) REQUIRE t.type_id IS UNIQUE;

// ─────────────────────────────────────────────────────────────────────────────
// 2. INDEXES (query hot-paths)
// ─────────────────────────────────────────────────────────────────────────────

CREATE INDEX textunit_sha IF NOT EXISTS       FOR (t:TextUnit)         ON (t.sha256);
CREATE INDEX textunit_lang IF NOT EXISTS      FOR (t:TextUnit)         ON (t.lang);
CREATE INDEX signal_layer IF NOT EXISTS       FOR (s:Signal)           ON (s.layer);
CREATE INDEX signal_cat IF NOT EXISTS         FOR (s:Signal)           ON (s.category);
CREATE INDEX signal_subcat IF NOT EXISTS      FOR (s:Signal)           ON (s.subcategory);
CREATE INDEX verdict_label IF NOT EXISTS      FOR (v:ClassifierVerdict) ON (v.label);
CREATE INDEX issue_state IF NOT EXISTS        FOR (i:Issue)            ON (i.state);
CREATE INDEX pr_state IF NOT EXISTS           FOR (p:PullRequest)      ON (p.state);

// ─────────────────────────────────────────────────────────────────────────────
// 3. MERGE TEMPLATES
// These are the authoritative write patterns used by GraphProjector.
// All use $params to stay parameterised and batch-friendly (UNWIND $rows AS row).
// ─────────────────────────────────────────────────────────────────────────────

// -- 3.1 Repository --------------------------------------------------------
// MERGE (r:Repository {full_name: $full_name})
//   ON CREATE SET r.created_at = $created_at,
//                 r.language   = $language,
//                 r.stars      = $stars,
//                 r.mined_at   = $mined_at
//   ON MATCH  SET r.stars      = $stars,
//                 r.mined_at   = $mined_at;

// -- 3.2 Actor -------------------------------------------------------------
// MERGE (a:Actor {login: $login})
//   ON CREATE SET a.type = $type, a.name = $name;

// -- 3.3 Issue + authorship + containment ---------------------------------
// MATCH (r:Repository {full_name: $repo})
// MERGE (i:Issue {repo: $repo, number: $number})
//   ON CREATE SET i.state = $state, i.created_at = $created_at,
//                 i.closed_at = $closed_at, i.labels = $labels
//   ON MATCH  SET i.state = $state, i.closed_at = $closed_at, i.labels = $labels
// MERGE (r)-[:CONTAINS]->(i)
// WITH i
// MATCH (a:Actor {login: $author_login})
// MERGE (a)-[:AUTHORED]->(i);

// -- 3.4 PullRequest (same pattern as Issue, with :PullRequest label) ----

// -- 3.5 Commit ------------------------------------------------------------
// MATCH (r:Repository {full_name: $repo})
// MERGE (c:Commit {sha: $sha})
//   ON CREATE SET c.authored_at = $authored_at, c.committed_at = $committed_at
// MERGE (r)-[:CONTAINS]->(c)
// WITH c
// MATCH (a:Actor {login: $author_login})
// MERGE (a)-[:AUTHORED]->(c);

// -- 3.6 Comment on Issue/PR ----------------------------------------------
// MATCH (parent) WHERE (parent:Issue OR parent:PullRequest)
//   AND parent.repo = $repo AND parent.number = $parent_number
// MERGE (c:Comment {github_comment_id: $comment_id})
//   ON CREATE SET c.kind = $kind, c.created_at = $created_at
// MERGE (parent)-[:HAS_COMMENT]->(c)
// WITH c
// MATCH (a:Actor {login: $author_login})
// MERGE (a)-[:AUTHORED]->(c);

// -- 3.7 TextUnit ----------------------------------------------------------
// The canonical text-level MERGE. parent_id is the stable id of the owning
// artefact (e.g. "issue:owner/repo:123" or "commit:<sha>").
// MATCH (parent) WHERE parent.id = $parent_id OR
//                      (parent:Issue       AND parent.repo = $repo AND parent.number = $parent_number) OR
//                      (parent:PullRequest AND parent.repo = $repo AND parent.number = $parent_number) OR
//                      (parent:Commit      AND parent.sha  = $parent_sha) OR
//                      (parent:Comment     AND parent.github_comment_id = $parent_comment_id)
// MERGE (u:TextUnit {id: $tu_id})
//   ON CREATE SET u.text = $text, u.lang = $lang,
//                 u.token_count = $token_count, u.sha256 = $sha256,
//                 u.created_at = $created_at, u.position = $position
// MERGE (parent)-[:HAS_TEXT {role: $role}]->(u);

// -- 3.8 Batch Signal write ------------------------------------------------
// NOTE: Neo4j property values must be primitives or arrays of primitives.
// A Signal's `payload` is a nested map, so it is JSON-serialised by the
// projector and stored as the string property `payload_json`.
// In analysis, parse it back with apoc.convert.fromJsonMap(sig.payload_json).
// UNWIND $signals AS s
// MATCH (u:TextUnit {id: s.text_unit_id})
// MERGE (sig:Signal {id: s.id})
//   ON CREATE SET sig.layer         = s.layer,
//                 sig.category      = s.category,
//                 sig.subcategory   = s.subcategory,
//                 sig.surface_form  = s.surface_form,
//                 sig.span_start    = s.span_start,
//                 sig.span_end      = s.span_end,
//                 sig.rule_id       = s.rule_id,
//                 sig.rule_version  = s.rule_version,
//                 sig.confidence    = s.confidence,
//                 sig.payload_json  = s.payload_json,
//                 sig.created_at    = datetime()
// MERGE (u)-[:HAS_SIGNAL]->(sig);

// -- 3.9 Link Signal to LexicalMarker (when layer='lexical') --------------
// MATCH (sig:Signal {id: $signal_id})
// MERGE (m:LexicalMarker {lemma: $lemma, lexicon_version: $lexicon_version})
//   ON CREATE SET m.pos = $pos, m.category = $category,
//                 m.subcategory = $subcategory, m.polarity = $polarity,
//                 m.source_citation = $source_citation
// MERGE (sig)-[:MATCHES_MARKER]->(m);

// -- 3.10 Link Signal to RhetoricalFigure (when layer='rhetorical') ------
// MATCH (sig:Signal {id: $signal_id})
// MERGE (f:RhetoricalFigure {figure_id: $figure_id})
//   ON CREATE SET f.family = $family, f.description = $description,
//                 f.source_citation = $source_citation
// MERGE (sig)-[:INSTANTIATES]->(f);

// -- 3.11 ClassifierVerdict ------------------------------------------------
// MATCH (u:TextUnit {id: $text_unit_id})
// MERGE (v:ClassifierVerdict {text_unit_id: $text_unit_id,
//                             model_id: $model_id,
//                             model_version: $model_version})
//   ON CREATE SET v.label = $label, v.confidence = $confidence,
//                 v.predicted_at = datetime()
//   ON MATCH  SET v.label = $label, v.confidence = $confidence,
//                 v.predicted_at = datetime()
// MERGE (u)-[:CLASSIFIED_AS]->(v);

// -- 3.12 Post-hoc IgnoranceType annotation -------------------------------
// Only assigned manually or by a downstream analysis step — never at ingest.
// MATCH (u:TextUnit {id: $text_unit_id})
// MERGE (t:IgnoranceType {type_id: $type_id})
//   ON CREATE SET t.name = $name, t.definition = $definition,
//                 t.source = $source, t.scope = $scope
// MERGE (u)-[r:TYPED_AS]->(t)
//   ON CREATE SET r.annotator = $annotator, r.confidence = $confidence,
//                 r.rationale = $rationale, r.annotated_at = datetime();

// ─────────────────────────────────────────────────────────────────────────────
// 4. SANITY-CHECK QUERIES (run after a first ingest)
// ─────────────────────────────────────────────────────────────────────────────

// 4.1 Node counts per label
// MATCH (n) RETURN labels(n) AS label, count(*) AS n ORDER BY n DESC;

// 4.2 Signals per layer
// MATCH (s:Signal) RETURN s.layer, count(*) AS n ORDER BY n DESC;

// 4.3 TextUnits without any signal (useful — these are "silent" units)
// MATCH (u:TextUnit) WHERE NOT (u)-[:HAS_SIGNAL]->()
// RETURN count(u) AS silent_units;

// 4.4 Classifier label distribution
// MATCH (v:ClassifierVerdict) RETURN v.label, count(*) AS n;

// 4.5 Orphan check — signals without a TextUnit (should be 0)
// MATCH (s:Signal) WHERE NOT (:TextUnit)-[:HAS_SIGNAL]->(s)
// RETURN count(s) AS orphan_signals;
