# Refined Research Questions v0.3 — FSE Paper (GraphRAG-NK)

*Supersedes `REFINED_RQS_v0.2.md`. Renumbered and re-scoped after the corpus
changed from an ad-hoc GitHub/Gmane crawl to the 12 curated, peer-reviewed MSR
datasets (`FRAMEWORK_DESIGN.md` §12).*

> **v0.3.1 restructure (2026-09-19).** The paper's centre of gravity moves from a
> taxonomy/lingua-linguistics inventory to **software-engineering communities,
> projects, and communication platforms**. RQ1 and RQ2 are demoted from
> headline research questions to **foundational baselines** (instrument audit +
> descriptive framework). The empirical core is a single overarching RQ with
> three macro, corpus-scale sub-RQs and one independent qualitative sub-RQ.
> The old hand-coded taxonomy questions (v0.3 RQ4a–c) and their predictions
> P1–P6 are **deferred to a companion study** — see §6. See CHANGELOG 2026-09-19.

---

## 1. Why this revision exists

v0.2 was written against an unbalanced, un-curated crawl: one repository
(`python/cpython`) and four Gmane lists. Its RQ6 carried a permanent "corpus is
not crossed" caveat, and its multi-actor claim (RQ4d/P4) had to be reconstructed
by hand because no threaded gold data was ingested. Neither limitation exists
under the new scope:

- **12 curated, peer-reviewed corpora** across **four communicative genres**
  (task tracking, peer-review email, synchronous chat, public Q&A), each with
  **within-genre replication** across platforms/projects.
- **Gold conversation structure** for the multi-actor claim: IRC reply links
  (`REPLIES_TO`), Slack disentangled conversations, Jira comment chains,
  curated-email `in_reply_to` chains.
- **An explicit expertise-asymmetry dataset** (OpenMent mentor–mentee) that no
  prior scope possessed.
- **Same projects across independent datasets** — 229 Apache project keys appear
  in *both* the MSR'23 and the MSR'22 Alternative-Jira corpora, giving a live
  cross-dataset replication substrate (see Sub-RQ 3, Arm B).

**The paper's central claim (v0.3.1).**

> How software-engineering discourse negotiates non-knowledge is a property of
> **where the negotiation happens**: the *communication platform* (its
> synchronicity, structural formality, and persistence), the *project's
> governance and technical domain*, and the *community's shared epistemic
> culture*. We quantify all three at corpus scale, test community-epistemic
> persistence with controlled cross-platform and cross-dataset replication, and
> characterise the communicative functions of non-knowledge qualitatively on a
> hand-coded, inter-rater-agreed sample.

Unchanged from v0.2/v0.3: signals are never collapsed; taxonomic labels are
post-hoc; every RQ must be falsifiable and map to a concrete measurement; the
classifier never gates other annotators; every rule lives in YAML.

---

## 2. Corpus and genres

The study scope is **exclusively the curated MSR corpora** (`FRAMEWORK_DESIGN.md`
§12); no ad-hoc GitHub mining or Gmane scraping is used. The **11 in-scope
corpus ids** map to four genres as follows (`source_corpus` / `corpus_id`
values are those the ingesters write; see `notebooks/03_rq_analysis.ipynb`
§2.0 for the registry).

| Genre | Corpus (`corpus_id`) | Platform | Dataset / paper |
|---|---|---|---|
| Task tracking | `apache-jira` | Jira | MSR'23 Jira Issues |
| Task tracking | `alternative-jira` | Jira | MSR'22 Alternative Jira |
| Task tracking | `numfocus` | GitHub-shaped activity | NumFOCUS |
| Review email | `curated-email-code-reviews` | email (kernel/ozlabs/ffmpeg) | Liang 2024 |
| Chat | `kummerfeld-irc` | IRC (+ new-domains) | Kummerfeld 2019 |
| Chat | `preethac-slack` | Slack | Chatterjee/Damevski/Kraft/Pollock |
| Chat | `disco` | Discord | DISCO-A (Muthu Subash) |
| Chat | `gittercom`, `livechat-gitter` | Gitter | GitterCom / LiveChatGitter |
| Q&A | `sotorrent` | Stack Overflow | SOTorrent (Baltes 2018) |
| *(role dataset)* | `openment` | GSoC issues/PRs | OpenMent |

Excluded from scope, stated once: `ocean_dataset` (disposable test corpus),
GitHub `raw_issues/...` and Gmane `gmane.*` data (old scope), **`bugsrepo`**
(links-only dataset; considered and retired 2026-08-31 — see
FRAMEWORK_DESIGN.md §12) and **`so-emotion-gold`** (too small, data
inconsistencies; considered and retired 2026-08-31 — see FRAMEWORK_DESIGN.md
§12). If any old-scope nodes are present in the database, every v0.3 query
filters on `source_corpus`/`corpus_id`.

**Declared design properties and confounds (in force in v0.3.1):**

- **Token normalisation is mandatory.** The four genres have different sampling
  designs and wildly different unit lengths (chat ≈ tens of tokens; Jira
  descriptions ≈ hundreds). Every rate is reported per 1,000 tokens; per-unit
  prevalence is reported separately and never substituted for a density claim.
- **Curated email is full-rate.** After the 2026-08-31 re-ingest the curated
  email corpus is the **full Patchwork pool (10,087,431 documents)**; the
  earlier ~44.8%-proportional hash-sampling note no longer applies
  (CHANGELOG 2026-08-31; the v0.2-era confound statement is retracted).
- **NumFOCUS is title-only.** The NumFOCUS activity stream carries only
  issue/PR **titles** (comment bodies and commit messages are absent by design).
  NumFOCUS is analysed as a *title register* and is excluded from cross-corpus
  body-text rate comparisons; within-corpus and venue-internal comparisons
  remain valid.
- **Cross-platform identity resolution is out of scope.** Actors are
  anonymised/namespaced per corpus (`FRAMEWORK_DESIGN.md` §4.8). Community
  comparisons (Sub-RQ 3) are made at the **community-of-practice / ecosystem**
  level, not at the individual-developer level.
- **Era is a confound.** Chat corpora carry no `created_at` on artefacts in the
  graph; era windows for cross-platform pairs are reported via a bounded
  Mongo-side join and disclosed, not analysed away.
- **Conversation structure is platform-dependent.** `REPLIES_TO` exists for
  curated email and IRC; Slack has `Conversation` blocks; Jira comment order is
  reconstructible; **Gitter and Discord have no conversation structure** — the
  qualitative trajectory dimension is UNCODABLE there (disclosed, see
  `CODING_MANUAL_v0.3.md` §10).

**Within-genre replication remains the design's credibility engine.** The genre
label is credible only if NK profiles vary less *within* a genre (across
platforms: IRC vs Slack vs Discord vs Gitter) than *between* genres (chat vs
tracker vs review email vs Q&A). This is tested in Sub-RQ 1.

---

## 3. Foundational baselines (context, not headline RQs)

These are the methodological and descriptive foundations the empirical sub-RQs
build on. They are reported in the non-knowledge related-work / framework
section (Baseline 1) and as an intermediate descriptive section between the
framework and the results (Baseline 2) — **not** as the paper's direct research
questions.

### Baseline 1 — How much can the borrowed taxonomies discriminate, on their own terms?
*(Instrument-level; literature-only, no corpus; ex-v0.3 RQ1, ex-v0.2 RQ4a.)*

- **Question.** Across Roberts (2013), Smithson (1989/1993), Gross (2010), and
  Wehling (2024): which categories are mutually non-discriminating, which share
  labels while denoting differently-scoped concepts, and how evenly is each
  taxonomy evidenced in its own primary literature?
- **Unit.** Category pair; taxonomy.
- **Operationalisation.** Direct from `TAXONOMY_CROSSWALK.md` and
  `SOURCES_AUDIT.md`, executed in `03_rq_analysis.ipynb` §3.1–3.4: relation
  counts by type; `NONE_POSSIBLE` pairs; per-category confidence vs per-taxonomy
  access; the low-confidence + low-priority category list.
- **Contribution.** The most attack-resistant result in the paper: it survives
  every objection to sampling, annotation, and corpus composition.

### Baseline 2 — What is the linguistic anatomy of non-knowledge in SE discourse?
*(Descriptive framework; corpus-wide, ex-v0.3 RQ2.)*

- **RQ2a (lexical).** Which lexical NK markers occur, at what token-normalised
  rate, and what fraction is SE-native (`repro_gap`, `opacity`, `spec_gap`,
  `doc_gap`, `code_comment_marker`, `non_deterministic_behaviour`)? Reported at
  signal and unit level, active and active+candidate, **per genre**.
- **RQ2b (morpho-syntactic).** How much NK is encoded by construction rather
  than keyword — the **cue-vs-scope gap** between bare-token and scoped
  (DependencyMatcher) rules — with the cue-vs-scope contingency per genre.
- **RQ2c (rhetorical).** Which metaphor/comparison/personification families
  express NK, and do SE-native figures (`opacity`, `hidden_extent`, `obscurity`)
  match the canonical figures (blind spot, knowledge gap) at comparable rates?
  The `opacity` double-count across RQ2a and RQ2c is disclosed, not silently
  avoided.

**Binding constraint.** Baseline 2 must be reported **per genre** (via the
parent artefact's `source_corpus`), never as a flat corpus mean.

---

## 4. The empirical core (overarching RQ + four sub-RQs)

**Overarching RQ — How do software engineering communities, projects, and
communication platforms shape the articulation and negotiation of
non-knowledge?**

> Sub-RQs 1–3 are **macro**, corpus-scale (≈40M TextUnits, ≈144M signals) and
> quantitative. Sub-RQ 4 is **micro**, an independent qualitative study on a
> hand-coded sample of 100 TextUnits with two independent raters.

### Sub-RQ 1 — Platform & medium affordances *(quantitative, corpus-scale)*

- **Question.** How does the articulation of non-knowledge vary across
  communication platforms with differing **synchronicity** (turn-taking speed:
  chat ≈ seconds vs tracker/email ≈ days), **structural formality** (message
  schema: free-form chat vs structured Jira fields), and **conversational
  persistence / accountability** (ephemeral scroll vs permanent audit trail)?
- **Unit.** Artefact source (corpus_id) / platform_id → genre.
- **Operationalisation.**
  - Token-normalised NK rate $R_{1k} = 1000 \cdot \sum \text{signals} /
    \sum \text{tokens}$; unit prevalence $P_{unit}$; layer-composition vector;
    SE-native marker concentration.
  - **Replication test (the credibility gate).** Compute an NK-signature vector
    per corpus_id (subcategory rates, layer mix, SE-native fraction); test
    within-genre vs between-genre profile distances by **permutation test on
    mean cosine distance** ($B = 10{,}000$), with effect size. Reported at venue
    level where venue counts permit; corpus level as sensitivity. **Genre
    claims are reported only where replication holds.**
- **Contribution.** Replaces v0.2's "uncrossed, therefore descriptive" caveat
  with a measured quantity: how SE negotiates not-knowing depends on where the
  negotiation happens.
- **Falsification condition.** If within-genre distance ≈ between-genre
  distance, the medium/genre variable is not real and the comparative layer
  collapses to corpus-level description (itself the informative result).

### Sub-RQ 2 — Project governance, technical domains & epistemic roles *(quantitative, corpus-scale)*

- **Question.** To what extent do a project's **governance model** and
  **technical domain** shape non-knowledge disclosure, and does the **speaker's
  epistemic role** within a project modulate it?
- **Unit.** Project `:Venue` (≥ a minimum unit threshold to avoid small-sample
  noise) grouped into governance and domain classes; role-tagged TextUnit for
  the role facet.
- **Operationalisation (live, in-notebook — no schema change).**
  - **Governance axis.** `alternative-jira` instances are classified live by a
    `GOVERNANCE_MAP` into **commercial/corporate** (`mojang`, `redhat`,
    `mongodb`, `qt`, `sonatype`, `spring`, `mariadb`, `jfrog`, `inteldaos`;
    >1.5M artefacts) vs **foundation/meritocratic** (`apache` instance + the
    whole `apache-jira` corpus; >2.1M artefacts). The `apache` instance is
    therefore **excluded from the commercial class** and reused as the
    cross-dataset replication set (Sub-RQ 3, Arm B).
  - **Domain axis.** Systems infrastructure (Linux Kernel email; Ubuntu IRC) vs
    scientific computing (NumFOCUS titles) vs web/application frameworks
    (Gitter).
  - **Role axis.** OpenMent mentor vs mentee; curated-email patch author vs
    reviewer (two independent role contrasts across two genres).
  - Compare groups on $R_{1k}$, SE-native gap density (`repro_gap`/`spec_gap`),
    and hedging ratio using non-parametric **Mann-Whitney U / Kruskal-Wallis**
    with **Holm-Bonferroni** correction.
- **Contribution.** Shows whether the epistemic climate of an SE project is
  governed by who runs it and what it builds, not just by which tool it uses.
- **Falsification condition.** If commercial and foundation projects show
  indistinguishable NK profiles within the same platform, the governance claim
  fails.

### Sub-RQ 3 — Controlled community & cross-dataset replication *(quantitative, corpus-scale)*

- **Question.** When the community/ecosystem (or the project set) is held
  constant, does the articulation of non-knowledge persist across platforms and
  across independent datasets, or does it adapt?
- **Unit.** Community-of-practice venue pair (Arm A); shared project key pair
  (Arm B).
- **Operationalisation (two arms).**
  - **Arm A — cross-platform community of practice.** Compare the Clojure
    community on Slack (`slack:preethac-slack:clojurians/clojure`) vs Discord
    (`discord:disco:Clojurians/clojure`) as **macro community-of-practice
    samples** (identical language, domain, and community label — not tracked
    individuals). Test whether the cross-platform distance for the *same*
    community is smaller than the within-platform distance across *different*
    communities. Secondary (weaker) ecosystem pair: Python (Slack `pythondev/help`
    vs Discord `Python/python-general` vs Stack Overflow `<python>` tag, via
    `metadata_json.tags`). Reported descriptively with effect sizes; **no
    p-values** — too few defensible pairs for inference.
  - **Arm B — cross-dataset project replication.** **Live set-intersection** of
    project keys shared between `apache-jira` (MSR'23) and `alternative-jira`
    (instance `apache`, MSR'22). Verified live: **229 shared projects**
    (Spark, Flink, HBase, Hive, Ambari, Kafka, Beam, Cassandra, …). Filter to
    projects ≥ a minimum artefact volume in *both* corpora and compare
    token-normalised NK rates and SE-native profiles across the two datasets to
    demonstrate instrument/extraction stability.
- **Contribution.** Arm A tests community-epistemic persistence across tools;
  Arm B tests measurement stability across peer-reviewed datasets.
- **Falsification condition.** If a shared project's NK profile differs more
  across the two datasets than across unrelated projects, the framework's
  measurement stability claim fails.

### Sub-RQ 4 — Communicative functions, referents & trajectories of non-knowledge *(independent, qualitative)*

- **Question.** When a software engineer articulates non-knowledge, what
  **communicative act** are they performing, what **technical object** does the
  gap refer to, and how is it **collaboratively resolved**?
- **Unit.** A detector-positive TextUnit in a multi-turn conversation, coded
  with surrounding thread context. The frame is **detector-positive** by design:
  this study characterises *how* expressed NK is communicated, not what the
  pipeline misses (coverage/blind-spot analysis is deferred with the old RQ4 —
  §6).
- **Sampling.** 100 TextUnits, each with ≥1 active NK signal, stratified **25
  per signal mechanism** (lexical / morpho-syntactic / rhetorical /
  classifier-detected) × **across the four genres** (chat, tracker, review
  email, Q&A). Chat units are restricted to platforms with threadable structure
  (IRC, Slack); Gitter/Discord units are excluded or marked `UNCODABLE` for the
  trajectory dimension. Deterministic selection (Cypher `ORDER BY u.id` + seeded
  NumPy RNG, seed 42). Exports `notebooks/qualitative_sample_100.csv`.
- **Coding (3 dimensions, 2 independent raters, Cohen's κ).**
  1. `communicative_function` — `HELP_SEEKING`, `HEDGING`, `SPECULATION`,
     `DEFECT_LOGGING`, `INSTRUCTION`.
  2. `epistemic_referent` — `CODE_RUNTIME`, `ENVIRONMENT`, `SPEC_INTENT`,
     `COMMUNITY_PROCESS`, `PERSONAL_GAP`.
  3. `conversational_trajectory` — `RESOLVED`, `ACTIONABLE_DEFERRED`,
     `OPEN_BOUNDARY`, `CONTESTED_OR_IGNORED`, `UNCODABLE_STRUCTURE_ABSENT`.
- **Reliability.** Two independent raters code all 100 units blind; Cohen's κ
  and observed agreement reported per dimension; disagreements adjudicated to
  consensus. Five pilot units (drawn from the same frame but **excluded** from
  the 100) calibrate the boundary rules first (total colleague exposure ≈105
  units).
- **Contribution.** The paper's qualitative "so what": a typology of what
  developers are *doing* when they express not-knowing, which objects resist
  understanding, and how uncertainty is (or is not) resolved in real SE
  collaboration.

---

## 5. Methodological boundary

### RQ5 — Where do the linguistic markers and the trained classifier disagree?
*(Layer 4; unchanged core, per-genre domain-shift frame.)*

- **Question.** Partitioning TextUnits by (marker-positive?) ×
  (classifier-positive?): what is the off-diagonal mass, what is each rule's
  precision on a labelled sample, and what do the disagreements reveal?
- **Operationalisation.** Per-`rule_id` precision; marker recall on
  classifier-positive units; rules ≥ τ promoted to `status:active`. The
  independence constraint is binding: the classifier is never a training target
  for marker weights.
- **New in v0.3 — domain-shift framing.** The 2×2 is reported **per genre**, and
  chat-register disagreement is interpreted, at least in part, as the classifier
  operating out-of-domain (RoBERTa on IRC slang is not RoBERTa on Jira prose).

---

## 6. Status of the old hand-coded taxonomy questions (RQ4a–c) and predictions P1–P6

**Deferred to a companion study (2026-09-19).** The v0.3 RQ4a–c instrument —
category-coverage on a hand-coded sample, coder-behaviour collapse tests, and
the multi-actor (P4) claim — and its pre-registered predictions **P1–P6**
(`CODING_MANUAL_v0.3.md` §7) remain **recorded but not tested in this paper**.
They are not retracted; they are moved out of scope so Sub-RQ 4 can stand as an
independent phenomenological qualitative study without inheriting the taxonomy
instrument's 400-unit frame. The `CODING_MANUAL_v0.3.md` §§1–9 decision tree is
retained as the (deferred) instrument; §10 documents the active Sub-RQ 4
codebook.

Consequence for scope discipline: Sub-RQ 4's detector-positive frame **does not**
measure blind spots/coverage of the marker pipeline. That measurement is part of
the deferred RQ4a and is explicitly not claimed here.

---

## 7. Scope discipline — what this paper deliberately does NOT ask

- **Temporal evolution of NK.** Next (graph-ML) paper.
- **Causal effect of NK on project outcomes.** Needs an outcome variable and an
  identification strategy; out of scope for a descriptive-linguistic paper.
- **Whether the taxonomies *should* be repaired.** A merged ignorance taxonomy
  needs validation on a second corpus; attempting it here converts a falsifiable
  measurement study into an unfalsifiable proposal. (Also deferred — §6.)
- **Blind-spot / marker coverage.** Deferred with RQ4a (§6).
- **NK vs emotion.** The SO emotion gold labels and OpenMent sentiment columns
  are deliberately **not** ingested (framework conflation). Explicitly deferred.

---

## 8. Execution order and dependencies

1. **Baseline 1** — runnable now, no corpus.
2. **Baseline 2** — runnable on the ingested graph; needs the corpus registry and
   per-genre aggregation via `source_corpus`.
3. **Sub-RQ 1** — runnable on the ingested graph; the rewritten permutation test
   is the deliverable.
4. **Sub-RQ 2** — runnable on the ingested graph; the live `GOVERNANCE_MAP` and
   domain labels are notebook-side (see `03_rq_analysis.ipynb` §4.4–4.6). Role
   facet needs OpenMent role metadata and curated-email `entity_type` metadata,
   joinable to `TextUnit.author_login`.
5. **Sub-RQ 3** — Arm A needs the two chat venue pairs (present); Arm B needs the
   live 229-project intersection (verified present). Descriptive; no inference.
6. **Sub-RQ 4** — blocked on the 100-unit sample export and the two-rater coding;
   the notebook builds the stratified frame now and reads coding CSVs if present.
7. **RQ5** — runnable on the ingested graph.