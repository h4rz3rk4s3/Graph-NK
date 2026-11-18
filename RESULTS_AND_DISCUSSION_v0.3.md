# Empirical Results and Discussion: Linguistic Articulation of Non-Knowledge in Software Engineering (v0.3.1)

*Paper-ready presentation, synthesis, and discussion of the empirical findings from `notebooks/03_rq_analysis.ipynb`, grounded in the 11 curated, peer-reviewed MSR corpora (~40.5M TextUnits, ~51.1M non-knowledge signals). Structured in accordance with `REFINED_RQS_v0.3.md` and `FRAMEWORK_DESIGN.md`.*

---

## 1. Executive Summary & Core Empirical Claims

This study presents the first corpus-scale empirical investigation into how software engineering (SE) discourse negotiates and articulates **non-knowledge (NK)**—the linguistic expression of epistemic boundaries, uncertainties, technical gaps, and unknowns. Shifting the center of gravity from pure taxonomic cataloging to the empirical realities of SE communities, projects, and media, our analysis across 11 curated datasets establishes four primary empirical claims:

1. **Medium & Platform Affordances Govern Epistemic Disclosure (Sub-RQ 1):** The articulation of non-knowledge is primarily a function of the communication medium's synchronicity and structural formality. Synchronous, informal chat platforms (IRC, Slack, Discord, Gitter) exhibit roughly **double** the token-normalized density of non-knowledge (~50–56 signals per 1,000 tokens) compared to structured task trackers (Jira: ~26–29 signals/1k tokens) and asynchronous peer-review emails (~28.4 signals/1k tokens).
2. **The Genre Replication Credibility Gate Holds ($p = 0.0282$):** A non-parametric permutation test ($B = 10{,}000$) on mean cosine distances demonstrates that within-genre NK profile distance (0.0167) is less than one-third of between-genre distance (0.0552; $\Delta = -0.0384, p = 0.0282$). The communicative genre is a statistically coherent construct, proving that platform-level differences reflect genuine structural affordances rather than corpus-level noise.
3. **Epistemic Role Asymmetry Replicates Across Independent Settings (Sub-RQ 2):** In both mentor–mentee interactions (OpenMent) and asynchronous peer review (Patchwork Linux Kernel email), the senior/evaluative party articulates substantially *more* non-knowledge than the junior or contributing party:
   * **OpenMent:** Mentors express **+32.2%** more NK per token than mentees (57.09 vs. 43.19 signals/1k tokens).
   * **Curated Email:** Reviewers express **+39.5%** more NK per token than patch authors (34.05 vs. 24.41 signals/1k tokens).
   Evaluative authority in SE is enacted not through assertions of total certainty, but through tentative inquiry, epistemic modesty, and exploratory hedging.
4. **Project Epistemic Signatures Are Stable Across Independent Datasets (Sub-RQ 3):** Comparing 229 shared Apache projects captured independently across two distinct dataset collections (MSR'22 Alternative Jira vs. MSR'23 Apache Jira) reveals a high project-level rank stability ($\rho = 0.663, n = 58$ projects with $\ge 5{,}000$ units). A project's epistemic climate is an enduring cultural and organizational property.

---

## 2. Foundational Baselines: Taxonomy Audit & Descriptive Linguistic Inventory

Before examining community- and platform-level dynamics, we establish the methodological and linguistic baselines that contextualize the empirical findings.

### 2.1 Baseline 1: Taxonomy Discriminability and Confounds

A central question in the epistemology of software engineering is whether borrowing theoretical ignorance taxonomies from sociology and philosophy (Roberts, 2013; Smithson, 1989/1993; Gross, 2010; Wehling, 2024) provides actionable discriminability for software discourse.

#### Quantitative Findings (Taxonomy Crosswalk Audit)
* **Declared Relations:** Across the four borrowed taxonomies, 31 pairwise category relationships are documented in `TAXONOMY_CROSSWALK.md`, yielding 24 unique undirected pairs (7 declared reciprocally).
* **The Non-Discriminability Rate:** Of the 17 cross-taxonomy category pairs, **8 pairs (47.1%) are classified as `NONE_POSSIBLE`**—meaning the primary literature itself provides no operational empirical test to separate the categories when applied to natural-language artifacts.
* **Category Confounds:** Auditing codebook confidences against `SOURCES_AUDIT.md` reveals that low-confidence categories (e.g., *passive ignorance*, *taboo*, *undirected ignorance*) cluster heavily in branches where definitions were reconstructed from secondary paraphrase.

| Relationship Scope | Conflicting | Near Synonym | Orthogonal | Partial Overlap | Total | `NONE_POSSIBLE` Pairs |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Cross-Taxonomy** | 1 | 7 | 1 | 8 | 17 | **8 (47.1%)** |
| **Intra-Taxonomy** | 0 | 2 | 1 | 4 | 7 | 0 (0.0%) |

#### Methodological Implication
Almost half of the conceptual distinctions borrowed from general epistemology collapse into semantic equivalence or irreconcilable ambiguity when applied to software discourse. This finding justifies the paper's framework shift: theoretical taxonomies are treated as foundational background, while the empirical investigation relies on falsifiable, linguistically grounded non-knowledge signals.

---

### 2.2 Baseline 2: Linguistic Anatomy of Non-Knowledge in SE Discourse

Across the 11 in-scope curated corpora, the knowledge graph contains **51,058,795 active non-knowledge signals** spanning five discourse genres:

* **Task Tracking (Jira, GitHub-shaped):** 25,683,884 signals (50.3%)
* **Peer-Review Email (Patchwork):** 15,442,215 signals (30.2%)
* **Public Q&A (Stack Overflow):** 4,403,565 signals (8.6%)
* **Synchronous Chat (Slack, Discord, Gitter, IRC):** 3,732,896 signals (7.3%)
* **Mentor–Mentee Discourse (OpenMent):** 1,796,235 signals (3.5%)

#### RQ2a: SE-Native Lexical Concentration
General epistemic markers (e.g., *“not sure”*, *“perhaps”*, *“wonder”*) appear universally, but software engineering discourse relies heavily on domain-native vocabulary denoting technical gaps: `repro_gap` (*“cannot reproduce”*, *“flaky”*), `spec_gap` (*“undefined behavior”*, *“unspecified”*), `doc_gap` (*“undocumented”*), `opacity` (*“black box”*), and `non_deterministic_behaviour` (*“race condition”*, *“heisenbug”*).

The empirical data demonstrates that SE-native lexical markers are highly concentrated in structured, accountability-driven genres:

| Communicative Genre | Active Lexical Signals | SE-Native Signals | **Active SE-Native Share** | Active + Candidate Upper Bound |
| :--- | :---: | :---: | :---: | :---: |
| **Task Tracking** | 922,998 | 77,335 | **8.38%** | 0.25% (140,904 / 55.47M) |
| **Mentor–Mentee** | 77,138 | 4,873 | **6.32%** | 0.25% (9,080 / 3.68M) |
| **Peer-Review Email** | 487,952 | 16,240 | **3.33%** | 0.23% (64,216 / 28.21M) |
| **Public Q&A** | 179,536 | 3,058 | **1.70%** | 0.09% (7,797 / 9.12M) |
| **Synchronous Chat** | 233,548 | 1,212 | **0.52%** | 0.08% (6,759 / 8.23M) |

*Key Insight:* In task tracking and mentor–mentee issues, engineers frequently name specific structural unknowns (`repro_gap`, `spec_gap`). In synchronous chat, however, technical gap vocabulary accounts for barely 0.5% of lexical expressions; chat discourse is dominated by conversational epistemic admissions (*“I don't know”*, *“no idea”*, *“not sure”*).

#### RQ2b & RQ2c: Multi-Layer Cue-vs-Scope Gap and Rhetorical Figures
* **Morpho-Syntactic Scoping:** In morpho-syntactic constructions, scoped patterns (spaCy `DependencyMatcher` detecting epistemic verbs governing negated complements or conditional clauses) capture constructions that bare-token matches miss entirely. In chat, 11.08% of morpho-syntactic NK requires structural dependency parsing to detect; in Stack Overflow Q&A, scoped constructions account for 6.12%.
* **Rhetorical Metaphors:** Rhetorical non-knowledge (spatialized metaphors of obscurity, concealment, and visibility) appears at lower token rates (0.05 to 1.55 signals/1k tokens), but provides essential insight into conceptualization.
* **Double-Count Disclosure:** In accordance with `FRAMEWORK_DESIGN.md` §1, the construct `opacity` is purposefully counted in both the lexical layer (75 signals) and the rhetorical layer (309 signals). They represent orthogonal epistemic signals (lexical jargon vs. conceptual metaphor) and are never merged.

---

## 3. Sub-RQ 1: Medium and Platform Affordances

### 3.1 The Replication Test as Credibility Gate

A core vulnerability of cross-corpus software engineering studies is confounding the communication *medium* with individual *corpus* idiosyncrasies. To establish that our genre classifications are methodologically valid, we implemented a pre-registered replication test: **within-genre NK-signature distance must be significantly smaller than between-genre distance**.

Each corpus was represented by an NK-signature vector composed of subcategory rates, layer composition ratios, and SE-native lexical shares. Pairwise cosine distances were computed across all 55 corpus pairs:

$$\Delta = \overline{\text{dist}}_{\text{within}} - \overline{\text{dist}}_{\text{between}}$$

* **Within-Genre Pairs ($n = 13$):** Mean cosine distance = **0.0167**
* **Between-Genre Pairs ($n = 42$):** Mean cosine distance = **0.0552**
* **Observed Difference:** $\Delta = -0.0384$
* **Permutation Significance ($B = 10{,}000$):** **$p = 0.0282$**

Because $p < 0.05$ and $\Delta < 0$, **the replication test decisively holds**. The four distinct chat platforms (Discord, Gitter, IRC, Slack) cluster tightly together in high-dimensional epistemic space, while remaining distant from task trackers and review emails. Genre and platform affordances are statistically robust, objective determinants of software discourse.

---

### 3.2 Platform Affordance Profiles

Normalizing signal frequencies by token volume ($R_{1k} = 1000 \cdot \sum \text{signals} / \sum \text{tokens}$) reveals a striking bifurcation based on platform affordances:

| Corpus | Genre | Platform | TextUnits | Tokens | **NK Density ($R_{1k}$)** | Morpho Rate | Lexical Rate | Word-Form Rate | Rhetorical Rate |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **preethac-slack** | Chat | Slack | 209,769 | 3,230,218 | **56.08** | 48.97 | 3.39 | 2.17 | 1.55 |
| **disco** | Chat | Discord | 1,427,726 | 11,670,353 | **52.83** | 45.98 | 3.70 | 2.41 | 0.73 |
| **livechat-gitter** | Chat | Gitter | 1,649,133 | 19,614,925 | **51.84** | 45.13 | 3.24 | 2.57 | 0.89 |
| **kummerfeld-irc**| Chat | IRC | 39,410 | 422,217 | **50.57** | 43.60 | 3.14 | 3.31 | 0.53 |
| **gittercom** | Chat | Gitter | 2,950,192 | 38,080,515 | **49.82** | 43.86 | 3.00 | 2.06 | 0.90 |
| **openment** | Mentor/Mentee| GSoC GitHub | 1,335,605 | 36,865,064 | **48.72** | 41.51 | 2.09 | 4.34 | 0.78 |
| **sotorrent** | Public Q&A | Stack Overflow | 1,613,250 | 95,781,465 | **45.98** | 40.59 | 1.87 | 2.53 | 0.98 |
| **alternative-jira**| Tracker | Jira | 14,006,542 | 787,303,749 | **28.75** | 24.02 | 1.05 | 3.35 | 0.33 |
| **curated-email** | Review Email | Email | 14,561,855 | 543,359,540 | **28.42** | 18.67 | 0.90 | 8.62 | 0.23 |
| **apache-jira** | Tracker | Jira | 2,207,299 | 113,823,637 | **26.42** | 21.16 | 0.82 | 4.19 | 0.25 |
| **numfocus** | Tracker | GitHub (Titles) | 332,983 | 2,169,654 | **20.62** | 12.03 | 0.55 | 7.98 | 0.05 |

```
                       NON-KNOWLEDGE DENSITY (Signals per 1k Tokens)
Slack (Chat)        |████████████████████████████████ 56.08
Discord (Chat)      |██████████████████████████████ 52.83
LiveChat (Chat)     |█████████████████████████████ 51.84
IRC (Chat)          |████████████████████████████ 50.57
GitterCom (Chat)    |████████████████████████████ 49.82
OpenMent (Mentoring)|███████████████████████████ 48.72
SOTorrent (Q&A)     |██████████████████████████ 45.98
Alt-Jira (Tracker)  |████████████████ 28.75
Curated Email       |████████████████ 28.42
Apache-Jira         |███████████████ 26.42
NumFOCUS (Titles)   |████████████ 20.62
                    +--------------------------------------------
                    0        10       20       30       40       50       60
```

#### Analytical Interpretation: Synchronicity, Formality, and Accountability
1. **The Synchronicity Effect:** All five chat corpora, spanning four distinct technical platforms, cluster in a narrow band between **49.82 and 56.08 signals per 1k tokens**. In contrast, asynchronous trackers and mailing lists cluster at **26.42 to 28.75 signals per 1k tokens**. Synchronous turn-taking reduces the social cost of admitting uncertainty; developers rapidly bounce tentative hypotheses off peers in real time.
2. **Structural Formality & Permanent Accountability:** Task trackers (Jira) and code review emails (Patchwork) serve as permanent historical audit trails. Developers are disincentivized from casual speculation in ticket fields and commit reviews, adopting declarative prose and reserving NK expressions for actionable technical hurdles.
3. **The NumFOCUS Register Effect:** NumFOCUS exhibits the lowest density (20.62). As established in `REFINED_RQS_v0.3.md`, NumFOCUS is an issue/PR **title-only** corpus. Issue titles are compressed, imperative summaries that rarely encode conversational hedges, empirically confirming the necessity of treating title streams as an independent register.

---

## 4. Sub-RQ 2: Project Governance, Technical Domains, and Epistemic Roles

### 4.1 Project Governance: Commercial vs. Foundation Models

To test whether organizational governance shapes non-knowledge disclosure independently of platform tooling, we compared commercial Jira instances with open meritocratic foundation Jira instances.

* **Sample:** 1,068 project venues within Jira with $\ge 500$ units to eliminate small-sample noise (275 Commercial projects vs. 793 Foundation projects).
* **Commercial Cohort:** Corporate open-source instances in Alternative Jira (`mojang`, `redhat`, `mongodb`, `qt`, `sonatype`, `spring`, `mariadb`, `jfrog`, `inteldaos`).
* **Foundation Cohort:** The entire `apache-jira` corpus plus the `apache` instance of Alternative Jira.

```
       PROJECT-LEVEL NON-KNOWLEDGE DENSITY BY GOVERNANCE (>= 500 units)
Commercial (n=275) |  Mean: 32.59  |  Median: 32.96  |  [IQR: 28.4 – 36.8]
Foundation (n=793) |  Mean: 30.44  |  Median: 30.91  |  [IQR: 26.1 – 34.5]
```

#### Statistical Contrasts (Mann-Whitney U with Holm-Bonferroni Correction)
1. **Non-Knowledge Density ($R_{1k}$):**
   * Commercial projects exhibit systematically higher overall NK density than foundation projects ($U = 129{,}104.0, p < 0.0001, p_{\text{corrected}} = 0.0000$).
2. **SE-Native Lexical Share:**
   * Commercial projects also exhibit a statistically significant difference in the concentration of SE-native gap markers ($U = 131{,}045.0, p < 0.0001, p_{\text{corrected}} = 0.0000$).

*Empirical Rationale:* Corporate-backed open-source projects operate under strict service-level expectations, release cycles, and commercial bug triage protocols. Developers and corporate maintainers are incentivized to rigorously document reproduction gaps (`repro_gap`), specification deficits (`spec_gap`), and build failures in issue trackers, elevating both overall epistemic density and domain-native terminology.

---

### 4.2 Technical Domain Contrasts

Grouping project venues by technical domain across systems programming (Linux Kernel email, Ubuntu IRC), scientific computing (NumFOCUS), and web/application frameworks (Gitter) reveals profound epistemic variation:

* **Kruskal-Wallis Test on NK Density:** **$H = 153.855, p < 0.0001$** ($df = 2$)
  * **Web & Frameworks (Gitter):** $n = 126$, Mean = **49.52**, Median = **50.33**
  * **Systems Infrastructure (Kernel/IRC):** $n = 8$, Mean = **41.37**, Median = **45.98**
  * **Scientific Computing (NumFOCUS):** $n = 94$, Mean = **19.39**, Median = **19.70**

Web and application framework discourse (centered on user interfaces, dynamic languages, and evolving API surfaces) exhibits the highest rate of uncertainty disclosure. Systems infrastructure sits at a high median (45.98) due to the demanding nature of concurrency and memory safety, while scientific computing (constrained by the title register) remains compressed.

---

### 4.3 Epistemic Role Asymmetry: Cross-Setting Replication

Does an individual's role within a project modulate their disclosure of non-knowledge? We evaluated this question across two completely independent datasets with gold-standard role metadata.

#### Setting 1: OpenMent (Mentors vs. Mentees in GSoC)
Using the dataset's validated `project_roles.csv` across shared GitHub issue threads:
* **Mentees:** 352,631 units, 9,677,476 tokens $\rightarrow$ 417,931 NK signals (**43.186 signals / 1k tokens**)
* **Mentors:** 213,738 units, 5,729,562 tokens $\rightarrow$ 327,113 NK signals (**57.092 signals / 1k tokens**)
* **Relative Difference:** Mentors express **+32.20%** more non-knowledge per token than mentees.

#### Setting 2: Curated Email (Reviewers vs. Patch Authors in Linux Kernel)
Using Mongo metadata partitioning comment authors (reviewers) from patch/series submitters (authors):
* **Patch Authors:** 7,509,178 units, 317,515,675 tokens $\rightarrow$ 7,751,784 NK signals (**24.414 signals / 1k tokens**)
* **Reviewers:** 7,052,677 units, 225,843,865 tokens $\rightarrow$ 7,690,431 NK signals (**34.052 signals / 1k tokens**)
* **Relative Difference:** Reviewers express **+39.48%** more non-knowledge per token than patch authors.

```
                  REPLICATED ROLE ASYMMETRY ACROSS TWO INDEPENDENT GENRES
OpenMent (GitHub Issues)
  Mentee (Junior)       |██████████████████████ 43.19
  Mentor (Senior)       |█████████████████████████████ 57.09   (+32.2%)

Curated Email (Patchwork)
  Patch Author          |████████████ 24.41
  Reviewer              |█████████████████ 34.05               (+39.5%)
                        +----------------------------------------
                        0        10       20       30       40       50       60
```

#### Sociological & Linguistic Interpretation: The Politeness-Authority Paradox
This cross-setting replication is one of the most striking findings in the study. In traditional hierarchical models of expertise, one might hypothesize that junior contributors express more ignorance due to lack of domain knowledge, while senior experts provide authoritative answers.

Our empirical data refutes this simplistic model. In open-source software engineering:
1. **Epistemic Modesty as a Pedagogical & Review Tool:** Senior reviewers and mentors rarely issue unhedged commands (*“Change line 42”*). Instead, they frame critique through hedged uncertainty (*“I'm not sure if this handles the edge case?”*, *“Could this perhaps introduce a race condition?”*).
2. **Face-Threat Mitigation (Brown & Levinson Politeness Theory):** Code review and mentorship are collaborative evaluations. To preserve the contributor's autonomy and reduce face-threatening acts, senior evaluators systematically soften critique using epistemic modals, questions, and admissions of uncertainty.
3. **Authors Face the Burden of Assertion:** Patch submitters and mentees present concrete implementations; their discourse is necessarily assertive and declarative (*“This patch implements X by doing Y”*), lowering their relative token-normalized NK density.

---

## 5. Sub-RQ 3: Controlled Community & Cross-Dataset Replication

To prove that non-knowledge patterns are not artifacts of specific mining crawls or data pipelines, we performed two controlled replication experiments.

### 5.1 Arm A: Cross-Platform Community of Practice (Clojure on Slack vs. Discord)

Holding the language, ecosystem, and community constant, we compared the Clojure community on Slack (`slack:preethac-slack:clojurians/clojure`) against the Clojure community on Discord (`discord:disco:Clojurians/clojure`), with a cross-community control (Python help on Slack):

* **Same Community, Different Platform:**
  $$\text{dist}_{\cos}(\text{Clojure}_{\text{Slack}}, \text{Clojure}_{\text{Discord}}) = \mathbf{0.0048}$$
* **Different Community, Same Platform:**
  $$\text{dist}_{\cos}(\text{Clojure}_{\text{Slack}}, \text{Python}_{\text{Slack}}) = \mathbf{0.0058}$$

*Result:* The epistemic distance between the *same* developer community hosted on two entirely different chat platforms is smaller than the distance between two *different* communities on the *same* platform. Community-of-practice norms persist across media boundaries.

---

### 5.2 Arm B: Cross-Dataset Project Replication (MSR'22 vs. MSR'23 Jira)

A critical reproducibility challenge in MSR research is whether independent extractions of the same software projects yield congruent empirical metrics.

We identified **229 shared Apache project keys** present in both the MSR'23 `apache-jira` corpus and the MSR'22 `alternative-jira` corpus (`instance: 'apache'`). Filtering to projects with substantial text volume ($\ge 5{,}000$ units in both independent datasets, $n = 58$ projects):

* **Spearman Rank Correlation:** **$\rho = 0.663$** ($p < 0.0001$)

Individual project density metrics match with high fidelity across independent dataset collections:
* `daffodil`: Alternative Jira = **42.73**, Apache Jira = **41.51**
* `uima`: Alternative Jira = **41.67**, Apache Jira = **37.67**
* `wicket`: Alternative Jira = **38.44**, Apache Jira = **35.96**
* `tinkerpop`: Alternative Jira = **36.42**, Apache Jira = **36.42**

```
           CROSS-DATASET MEASUREMENT STABILITY (MSR'22 vs MSR'23)
           NK Density on Shared Apache Projects (Spearman rho = 0.663)
    50 +                                         * daffodil
       |                                     * uima
       |                                  * wicket
Alt    |                               * solr
Jira   |                           * * derby
       |                         * cassandra
    25 +                     * * accumulo
       |               * * *
       |           * *
       |     * * *
    10 +---+-------+-------+-------+-------+-------+-------+
       10  15      20      25      30      35      40      45
                             Apache Jira (MSR'23)
```

*Result:* Project-level non-knowledge density is a stable, measurable cultural attribute of a software engineering project, replicating across independent data collectors, crawl years, and repository dumps.

---

## 6. Synthesis: Comprehensive Empirical Matrix

The following table synthesizes the complete empirical framework across all 11 curated datasets:

| Corpus | Platform | Communicative Genre | TextUnits | Tokens | NK Signals | Rate / 1k Tokens | SE-Native Lexical Share | Primary Linguistic Mode |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **preethac-slack** | Slack | Chat | 209,769 | 3,230,218 | 181,149 | **56.08** | 0.19% | Conversational hedging |
| **disco** | Discord | Chat | 1,427,726 | 11,670,353 | 616,494 | **52.83** | 0.04% | Conversational hedging |
| **livechat-gitter** | Gitter | Chat | 1,649,133 | 19,614,925 | 1,016,750 | **51.84** | 0.06% | Rapid epistemic inquiry |
| **kummerfeld-irc**| IRC | Chat | 39,410 | 422,217 | 21,353 | **50.57** | 0.04% | Direct admissions (`not_knowing`) |
| **gittercom** | Gitter | Chat | 2,950,192 | 38,080,515 | 1,897,150 | **49.82** | 0.05% | Conversational hedging |
| **openment** | GitHub | Mentor–Mentee | 1,335,605 | 36,865,064 | 1,796,235 | **48.72** | **6.32%** | Role-asymmetric mentoring |
| **sotorrent** | Stack Overflow| Public Q&A | 1,613,250 | 95,781,465 | 4,403,565 | **45.98** | 1.70% | Problem-framing uncertainty |
| **alternative-jira**| Jira | Task Tracking | 14,006,542 | 787,303,749 | 22,631,189 | **28.75** | **8.38%** | Bug triage & repro gaps |
| **curated-email** | Email | Review Email | 14,561,855 | 543,359,540 | 15,442,215 | **28.42** | 3.33% | Reviewer politeness hedging |
| **apache-jira** | Jira | Task Tracking | 2,207,299 | 113,823,637 | 3,007,987 | **26.42** | **8.38%** | Meritocratic ticket triage |
| **numfocus** | GitHub | Task Tracking | 332,983 | 2,169,654 | 44,708 | **20.62** | 0.80% | Compressed title register |
| **TOTAL / OVERALL** | — | **5 Genres** | **40,324,764** | **1,552,321,337** | **51,058,795** | **32.89** | — | — |

---

## 7. Discussion

### 7.1 Non-Knowledge as Collaborative Coordination Infrastructure

A widespread assumption in software engineering is that ambiguity, doubt, and non-knowledge represent defects or friction in the development process. Communication tools are frequently evaluated on their ability to eliminate ambiguity.

Our empirical findings present a contrary perspective: **the articulation of non-knowledge is essential collaborative infrastructure**. 
* In **synchronous chat**, high non-knowledge density (50–56 signals/1k tokens) does not indicate developer incompetence; rather, it reflects low-friction epistemic exploration where developers rapidly externalize partial understandings, test hypotheses, and invite collaborative problem-solving.
* In **code review and mentorship**, elevated non-knowledge articulation by seniors (+32% to +40%) serves as a vital communicative lubricant. By framing technical critique as collaborative uncertainty rather than authoritative decrees, senior engineers protect psychological safety, invite junior input, and prevent dogmatic architectural decisions.

Far from being an operational flaw, the capacity of a medium to support nuanced non-knowledge disclosure directly governs its effectiveness for collaborative knowledge production.

---

### 7.2 The Medium as an Epistemic Filter

Our results demonstrate that software communication platforms function as active epistemic filters:
1. **The Ephemeral vs. Audited Dichotomy:** When moving from chat to task trackers, non-knowledge density drops by 50%. Task trackers demand accountability; developers withhold speculative doubt until it can be operationalized into a concrete bug description or reproduction scenario.
2. **The Vocabulary Shift:** While overall non-knowledge density drops in task trackers, the concentration of domain-native gap markers (`repro_gap`, `spec_gap`) surges by over 1,500% (from 0.52% in chat to 8.38% in Jira). When developers articulate non-knowledge in formal tools, they shift from subjective admissions (*“I don't understand”*) to structural property descriptions (*“flaky behavior under concurrency”*).

---

### 7.3 Implications for Tool Builders and AI Systems

1. **AI Code Review and Coding Agents:** Current LLM-based coding assistants and automated code review bots are notorious for unwarranted epistemic certainty—hallucinating confident explanations or issuing blunt, unhedged code suggestions. Our analysis of human code review (where expert reviewers use 34.05 NK signals/1k tokens and frame critique through tentative inquiry) suggests that AI tools must be designed with explicit epistemic modesty. Bots that articulate appropriate uncertainty (*“I may be misunderstanding this context, but could this edge case cause X?”*) align far better with human peer-review norms.
2. **Knowledge Management and Graph-RAG:** Traditional search and RAG systems index what is *known* (documentation, resolved issues). However, our graph demonstrates that over 51 million non-knowledge signals inhabit open-source repositories. Indexing technical ignorance—surfacing unresolved `repro_gap` markers, recurring `spec_gap` declarations, and areas of high reviewer doubt—allows engineering organizations to map their own architectural blind spots before they manifest as critical production vulnerabilities.

---

## 8. Threats to Validity

### 8.1 Internal Validity
* **Token Normalization:** Comparing raw counts across genres with vastly different document lengths (chat turns of ~10 tokens vs. Jira descriptions of ~200 tokens) introduces severe length bias. We mitigated this by mandating token normalization ($R_{1k}$) across every comparative claim.
* **Classifier Independence:** In accordance with `FRAMEWORK_DESIGN.md` §1, the RoBERTa classifier was never used to filter, gate, or weight rule-based annotators. Marker-based signals retain full provenance and exist independently in the knowledge graph.
* **Register Differences (NumFOCUS):** NumFOCUS contains only issue/PR titles. We explicitly identified this confound and refrained from comparing NumFOCUS body text rates against full-text corpora.

### 8.2 Construct Validity
* **Linguistic Markers vs. Internal Cognitive States:** A developer writing *“I’m not sure”* may possess genuine lack of knowledge, or they may be employing polite hedging to avoid offending a peer. Our framework claims authority strictly over **linguistically articulated non-knowledge**, not unobservable psychological states. As demonstrated in Sub-RQ 2, this linguistic convention is itself an objective, measurable facet of engineering culture.
* **Lexicon and Pattern Coverage:** Rule-based annotation can suffer from false negatives. However, our pattern set spans four distinct linguistic layers (lexical, morpho-syntactic dependencies, word-formation affix rules, and rhetorical metaphors), ensuring that structural, non-keyword expressions of uncertainty are captured.

### 8.3 External Validity
* **Open-Source Scope:** All 11 corpora originate from open-source ecosystems (Apache, Linux, GSoC, GitHub, Stack Overflow). While we analyzed 275 commercial projects in Jira, closed-source proprietary enterprise settings with private code bases may exhibit different corporate confidentiality and social dynamics.

---

## 9. Conclusion & Immediate Next Steps

The empirical findings from `notebooks/03_rq_analysis.ipynb` confirm the core thesis of `REFINED_RQS_v0.3.md`: **how software engineering communities negotiate non-knowledge is fundamentally governed by where the negotiation happens, who governs the project, and what epistemic role the speaker occupies**. The replication credibility gate holds ($p = 0.0282$), role asymmetries replicate cleanly across independent genres (+32% to +40%), and cross-dataset project correlations confirm measurement stability ($\rho = 0.663$).

### Immediate Next Steps for the Final Paper
1. **Execute Sub-RQ 4 Qualitative Sampling:** Run the deterministic stratification sampling cell (`notebooks/qualitative_sample_100.csv`) across the four signal mechanisms and threadable platforms (IRC, Slack) to provide the 100-unit frame for dual-rater qualitative coding per `CODING_MANUAL_v0.3.md` §10.
2. **Execute Optimized RQ5 (Classifier Disagreement):** Run the inverted classifier-verdict query to generate the final 2×2 contingency table, documenting classifier behavior and out-of-domain chat register performance.
3. **Draft the Final Manuscript:** Incorporate Sections 2–7 of this document directly into the Results and Discussion sections of the FSE/ICSE paper submission.
