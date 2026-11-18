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

// Mailing-list layer (Webis Gmane Email Corpus 2019) — v0.6
CREATE CONSTRAINT mailinglist_name IF NOT EXISTS
  FOR (m:MailingList) REQUIRE m.name IS UNIQUE;
// m.name is the Gmane group name, e.g. "gmane.comp.python.devel".

CREATE CONSTRAINT email_urn IF NOT EXISTS
  FOR (e:EmailMessage) REQUIRE e.urn IS UNIQUE;
// e.urn is the corpus document UUID ("urn:uuid:..."), guaranteed unique.
// message_id is NOT unique-constrained: it can be missing or duplicated in
// crawled mail archives; it is indexed below for threading lookups.

// Multi-platform corpus layer v0.8 (FRAMEWORK_DESIGN §4.8)
CREATE CONSTRAINT platform_id IF NOT EXISTS
  FOR (p:Platform) REQUIRE p.platform_id IS UNIQUE;

CREATE CONSTRAINT venue_id IF NOT EXISTS
  FOR (v:Venue) REQUIRE v.venue_id IS UNIQUE;

CREATE CONSTRAINT corpus_id IF NOT EXISTS
  FOR (c:Corpus) REQUIRE c.corpus_id IS UNIQUE;

CREATE CONSTRAINT conversation_id IF NOT EXISTS
  FOR (c:Conversation) REQUIRE c.conversation_id IS UNIQUE;

// Every :Artefact (any platform/family) has a globally namespaced record_id
// equal to its parent_id in the TextUnit stream. It doubles as the parent
// lookup key for TextUnit projection. Only nodes carrying the :Artefact label
// are constrained — legacy pre-migration GitHub nodes are excluded until the
// v0.8 backfill labels them (scripts/migrate_v0.8.cypher).
CREATE CONSTRAINT artefact_record_id IF NOT EXISTS
  FOR (a:Artefact) REQUIRE a.record_id IS UNIQUE;

// The v0.8 external artefact families are upserted by MERGE on their OWN label
// (graph_projector._upsert_chat_artefact etc.), and a constraint on :Artefact
// alone does NOT accelerate a MERGE (m:ChatMessage {...}) — that would fall back
// to a full label scan that grows linearly with the corpus (the Phase-0
// slowdown, CHANGELOG 2026-08-16). Each family therefore carries its own
// record_id uniqueness constraint. These are the SAME record_ids as the
// :Artefact constraint (nodes carry both labels), so they add no semantic
// key — they only give MERGE an O(1) seek path.
CREATE CONSTRAINT chatmessage_record_id IF NOT EXISTS
  FOR (m:ChatMessage) REQUIRE m.record_id IS UNIQUE;

CREATE CONSTRAINT jiraissue_record_id IF NOT EXISTS
  FOR (j:JiraIssue) REQUIRE j.record_id IS UNIQUE;

CREATE CONSTRAINT bugzillaissue_record_id IF NOT EXISTS
  FOR (b:BugzillaIssue) REQUIRE b.record_id IS UNIQUE;

CREATE CONSTRAINT sopost_record_id IF NOT EXISTS
  FOR (p:StackOverflowPost) REQUIRE p.record_id IS UNIQUE;

// ─────────────────────────────────────────────────────────────────────────────
// 2. INDEXES (query hot-paths)
// ─────────────────────────────────────────────────────────────────────────────

CREATE INDEX textunit_sha IF NOT EXISTS       FOR (t:TextUnit)         ON (t.sha256);
CREATE INDEX textunit_lang IF NOT EXISTS      FOR (t:TextUnit)         ON (t.lang);
CREATE INDEX signal_layer IF NOT EXISTS       FOR (s:Signal)           ON (s.layer);
CREATE INDEX signal_cat IF NOT EXISTS         FOR (s:Signal)           ON (s.category);
CREATE INDEX signal_subcat IF NOT EXISTS      FOR (s:Signal)           ON (s.subcategory);
CREATE INDEX signal_status IF NOT EXISTS      FOR (s:Signal)           ON (s.status);
CREATE INDEX verdict_label IF NOT EXISTS      FOR (v:ClassifierVerdict) ON (v.label);
CREATE INDEX issue_state IF NOT EXISTS        FOR (i:Issue)            ON (i.state);
CREATE INDEX pr_state IF NOT EXISTS           FOR (p:PullRequest)      ON (p.state);
CREATE INDEX email_message_id IF NOT EXISTS   FOR (e:EmailMessage)     ON (e.message_id);
CREATE INDEX email_group IF NOT EXISTS        FOR (e:EmailMessage)     ON (e.group);
CREATE INDEX email_in_reply_to IF NOT EXISTS  FOR (e:EmailMessage)     ON (e.in_reply_to);

// v0.8 multi-platform hot-paths
CREATE INDEX artefact_platform IF NOT EXISTS  FOR (a:Artefact)         ON (a.platform_id);
CREATE INDEX artefact_corpus IF NOT EXISTS    FOR (a:Artefact)         ON (a.source_corpus);
CREATE INDEX artefact_kind IF NOT EXISTS      FOR (a:Artefact)         ON (a.artefact_kind);
CREATE INDEX artefact_venue IF NOT EXISTS     FOR (a:Artefact)         ON (a.venue_id);
CREATE INDEX conversation_venue IF NOT EXISTS FOR (c:Conversation)     ON (c.venue_id);

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
// v0.2 (MARKER_REVIEW.md §3.5): sig.weight (float, analysis-time confidence
// hint, may be null — never filtered on at ingest) and sig.status
// ("active" | "candidate" — candidate rules ARE ingested with full
// provenance; excluding them from headline counts is an analysis-time
// convention, not an ingest-time filter). ON MATCH SET refreshes weight/
// status so a later re-run (e.g. after empirical calibration promotes a
// rule) updates existing nodes without requiring a rebuild.
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
//                 sig.weight        = s.weight,
//                 sig.status        = s.status,
//                 sig.payload_json  = s.payload_json,
//                 sig.created_at    = datetime()
//   ON MATCH  SET sig.weight        = s.weight,
//                 sig.status        = s.status
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

// -- 3.13 MailingList / EmailMessage (Webis Gmane, v0.6) --------------------
// MERGE (m:MailingList {name: $group});
// MERGE (e:EmailMessage {urn: $urn})
//   ON CREATE SET e.message_id = $message_id, e.subject = $subject,
//                 e.date = $date, e.group = $group, e.list_id = $list_id,
//                 e.in_reply_to = $in_reply_to, e.references = $references,
//                 e.lang = $lang;
// MATCH (m:MailingList {name: $group}) MATCH (e:EmailMessage {urn: $urn})
// MERGE (m)-[:CONTAINS]->(e);
// MATCH (a:Actor {login: $sender}) MATCH (e:EmailMessage {urn: $urn})
// MERGE (a)-[:AUTHORED]->(e);
// TextUnits: MATCH (parent:EmailMessage {urn: $urn}) ... (same HAS_TEXT as §3.7;
// role = corpus segment label | "subject"; id = "email:<urn>:<role>:<position>").
// Threading (enrichment/email_threading.py, after ingest):
// MATCH (reply:EmailMessage) WHERE reply.in_reply_to IS NOT NULL
// MATCH (parent:EmailMessage {message_id: reply.in_reply_to})
// MERGE (reply)-[:REPLIES_TO]->(parent);

// ─────────────────────────────────────────────────────────────────────────────
// 3.14 Multi-platform corpus layer (v0.8)
// ─────────────────────────────────────────────────────────────────────────────
// All new corpora write through these templates. Every external-artefact write
// MUST also set :Artefact (+ family + platform labels via apoc.create.addLabels)
// and the platform_id / venue_id / corpus_id / source_corpus / artefact_kind /
// record_id properties — that is the only thing that makes RQ6 platform
// comparison possible. Existing GitHub / Gmane / OCEAN writes get the same
// treatment by the projector and by scripts/migrate_v0.8.cypher.

// -- 3.14.1 Platform / Venue / Corpus (cheap, per-artefact idempotent) -------
// MERGE (p:Platform {platform_id: $platform_id})
//   ON CREATE SET p.name = $platform_name, p.kind = $platform_kind;
// MERGE (v:Venue {venue_id: $venue_id})
//   ON CREATE SET v.platform_id = $platform_id, v.corpus_id = $corpus_id,
//                 v.external_id = $venue_external_id, v.name = $venue_name;
// MERGE (p)-[:HAS_VENUE]->(v);
// MERGE (c:Corpus {corpus_id: $corpus_id})
//   ON CREATE SET c.name = $corpus_name, c.version = $corpus_version,
//                 c.citation = $corpus_citation, c.license = $corpus_license,
//                 c.source_uri = $corpus_uri;
// MERGE (c)-[:COVERS]->(v);

// -- 3.14.2 Issue-like external artefacts -----------------------------
// Jira:
// MERGE (i:JiraIssue {record_id: $record_id})
//   ON CREATE SET i.project_key = $project_key, i.issue_key = $issue_key,
//                 i.state = $state, i.issue_type = $issue_type,
//                 i.priority = $priority, i.resolution = $resolution,
//                 i.created_at = $created_at, i.platform_id = $platform_id,
//                 i.venue_id = $venue_id, i.corpus_id = $corpus_id,
//                 i.source_corpus = $corpus_id, i.artefact_kind = 'jira_issue',
//                 i.metadata_json = $metadata_json;
// MERGE (v:Venue {venue_id: $venue_id})-[:CONTAINS]->(i);
// (Bugzilla identical with label :BugzillaIssue, artefact_kind 'bugzilla_issue',
//  and product/summary fields.)
// Labels: CALL apoc.create.addLabels(i, $labels)

// -- 3.14.3 Message-like external artefacts ---------------------------
// MERGE (m:ChatMessage {record_id: $record_id})
//   ON CREATE SET m.channel = $channel, m.sequence = $sequence,
//                 m.sent_at = $created_at, m.platform_id = $platform_id,
//                 m.venue_id = $venue_id, m.corpus_id = $corpus_id,
//                 m.source_corpus = $corpus_id, m.artefact_kind = $artefact_kind,
//                 m.metadata_json = $metadata_json;
// MERGE (v:Venue {venue_id: $venue_id})-[:CONTAINS]->(m);
// IF conversation_id present:
//   MERGE (c:Conversation {conversation_id: $conversation_id})
//     ON CREATE SET c.platform_id = $platform_id, c.venue_id = $venue_id,
//                   c.corpus_id = $corpus_id, c.source_label = $conversation_label;
//   MERGE (v)-[:HAS_CONVERSATION]->(c);
//   MERGE (c)-[:CONTAINS]->(m);
// Labels: CALL apoc.create.addLabels(m, $labels)   // e.g. [SlackMessage, MessageArtefact, Artefact]

// -- 3.14.4 Stack Overflow posts ---------------------------------------
// MERGE (p:StackOverflowPost {record_id: $record_id})
//   ON CREATE SET p.post_type = $post_type, p.external_id = $external_id,
//                 p.question_id = $question_id, p.parent_post_id = $parent_post_id,
//                 p.created_at = $created_at, ...platform/corpus props as above;
// MERGE (v:Venue {venue_id: $venue_id})-[:CONTAINS]->(p);
// Labels: CALL apoc.create.addLabels(p, [StackOverflowQuestion|StackOverflowAnswer|
//                                        StackOverflowComment, PostArtefact, Artefact])
// ANSWER edge (only when source provides it):
// MATCH (a:StackOverflowAnswer {record_id: $answer_record_id})
// MATCH (q:StackOverflowQuestion {record_id: $question_record_id})
// MERGE (a)-[:ANSWERS]->(q);

// -- 3.14.5 ORPHAN / PARENT MATCH for TextUnits of external artefacts ---
// TextUnit projection for new parent_types uses record_id directly:
// MATCH (parent:Artefact {record_id: $parent_record_id})
// MERGE (u:TextUnit {id: $tu_id}) ... (rest identical to §3.7)

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

// 4.6 v0.8 — per-platform artefact / TextUnit / Signal counts
// MATCH (a:Artefact)-[:HAS_TEXT]->(u:TextUnit)
// OPTIONAL MATCH (u)-[:HAS_SIGNAL]->(s:Signal)
// RETURN a.platform_id, a.artefact_kind, count(DISTINCT a) AS artefacts,
//        count(DISTINCT u) AS units, count(s) AS signals
// ORDER BY a.platform_id, a.artefact_kind;

// 4.7 v0.8 — artefacts missing the shared label set (should be 0 after backfill)
// MATCH (a:Artefact) WHERE a.platform_id IS NULL OR a.record_id IS NULL
// RETURN count(a) AS mislabelled_artefacts;

// 4.8 v0.8 — TextUnits whose parent is missing (should be 0)
// MATCH (u:TextUnit)
// WHERE u.parent_type IN ['jira_issue','bugzilla_issue','chat_message','so_post']
//   AND NOT EXISTS { MATCH (:Artefact {record_id: u.parent_id}) }
// RETURN count(u) AS orphan_external_units;

// 4.9 v0.8 — per-corpus node counts (visual check of which corpora are loaded)
// MATCH (a:Artefact) RETURN a.source_corpus, count(*) AS n ORDER BY n DESC;
