// ============================================================================
// GraphRAG-NK — v0.8 backfill migration (run ONCE on an existing graph).
// ----------------------------------------------------------------------------
// Brings premigrated GitHub / Gmane / OCEAN nodes onto the multi-platform
// :Artefact layer so RQ6 platform-comparison queries cover the whole graph,
// not just the new corpora (see FRAMEWORK_DESIGN.md §4.8 / AGENTS.md §5.6).
//
//   cypher-shell < scripts/migrate_v0.8.cypher
//
// Idempotent: guarded by `WHERE NOT n:Artefact`, safe to re-run.
// CRITICAL: run AFTER applying ontology/ontology.cypher (the artefact_record_id
// constraint must exist first, because these SETs feed it).
// ============================================================================

// 1. GitHub issues/pull-requests/commits → Artefact family + platform labels.
MATCH (i:Issue) WHERE NOT i:Artefact
SET i:Artefact:IssueArtefact:GitHubIssue,
    i.record_id = 'issue:' + i.repo + ':' + toString(i.number),
    i.platform_id = 'github', i.venue_id = 'github:' + i.repo,
    i.source_corpus = 'github', i.artefact_kind = 'issue'
SET i.corpus_id = 'github';

MATCH (p:PullRequest) WHERE NOT p:Artefact
SET p:Artefact:IssueArtefact:PullRequestArtefact:GitHubPullRequest,
    p.record_id = 'pr:' + p.repo + ':' + toString(p.number),
    p.platform_id = 'github', p.venue_id = 'github:' + p.repo,
    p.source_corpus = 'github', p.artefact_kind = 'pull_request'
SET p.corpus_id = 'github';

MATCH (c:Commit) WHERE NOT c:Artefact
SET c:Artefact:CommitArtefact:GitHubCommit,
    c.record_id = 'commit:' + c.sha,
    c.platform_id = 'github', c.venue_id = 'github-commits',
    c.source_corpus = 'github', c.artefact_kind = 'commit'
SET c.corpus_id = 'github';

// 2. Email nodes (Gmane namespace = 'gmane:', OCEAN namespace = 'ocean:').
MATCH (e:EmailMessage) WHERE NOT e:Artefact
SET e:Artefact:MessageArtefact:EmailMessage,
    e.record_id = 'email:' + e.urn,
    e.platform_id = 'mailing_list',
    e.source_corpus = CASE WHEN e.urn STARTS WITH 'ocean:' THEN 'ocean'
                           WHEN e.urn STARTS WITH 'gmane:' THEN 'gmane'
                           ELSE 'email' END,
    e.artefact_kind = 'email'
SET e.corpus_id = e.source_corpus;

// 3. Repositories and mailing lists become Venues under the Platform layer.
MATCH (r:Repository) WHERE NOT r:Venue
MERGE (p:Platform {platform_id: 'github'}) ON CREATE SET p.name = 'GitHub', p.kind = 'issue_tracker'
MERGE (v:Venue {venue_id: 'github:' + r.full_name})
  ON CREATE SET v.platform_id = 'github', v.corpus_id = 'github', v.external_id = r.full_name
MERGE (p)-[:HAS_VENUE]->(v)
WITH r, v
// re-parent existing GitHub artefacts under the Venue (MOVE the CONTAINS edge:
// artefact is contained by the Venue, not by the Repository node alone).
MATCH (r)-[old:CONTAINS]->(a:Artefact)
WHERE a.venue_id = 'github:' + r.full_name
MERGE (v)-[:CONTAINS]->(a);

MATCH (m:MailingList) WHERE NOT m:Venue
MERGE (p:Platform {platform_id: 'mailing_list'}) ON CREATE SET p.name = 'Mailing list', p.kind = 'email'
MERGE (v:Venue {venue_id: 'mailing_list:' + m.name})
  ON CREATE SET v.platform_id = 'mailing_list', v.corpus_id = 'gmane', v.external_id = m.name
MERGE (p)-[:HAS_VENUE]->(v)
WITH m, v
MATCH (m)-[old:CONTAINS]->(e:Artefact)
MERGE (v)-[:CONTAINS]->(e);

// 4. Corpus provenance nodes (one per detected source_corpus).
MERGE (c:Corpus {corpus_id: 'github'}) ON CREATE SET c.name = 'GitHub mined corpora';
MERGE (c:Corpus {corpus_id: 'gmane'})  ON CREATE SET c.name = 'Webis Gmane Email Corpus 2019';
MERGE (c:Corpus {corpus_id: 'ocean'})  ON CREATE SET c.name = 'OCEAN mailing lists';
MATCH (corp:Corpus) MATCH (ven:Venue) WHERE ven.corpus_id = corp.corpus_id
MERGE (corp)-[:COVERS]->(ven);

// 5. Report (for your records).
MATCH (a:Artefact) RETURN a.platform_id, a.artefact_kind, count(*) AS n
ORDER BY a.platform_id, a.artefact_kind;