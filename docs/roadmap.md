# Roadmap: expanding from AER to the top five journals

The current product covers the *American Economic Review* (AER), 2000–present. The
next major scope change is to cover the five journals most often treated as the
top five in economics:

| Code | Journal | ISSN (print) | Publisher (2000–present) |
|---|---|---|---|
| AER | American Economic Review | 0002-8282 | AEA |
| QJE | Quarterly Journal of Economics | 0033-5533 | MIT Press / Oxford |
| JPE | Journal of Political Economy | 0022-3808 | University of Chicago Press |
| RES | Review of Economic Studies | 0034-6527 | Oxford University Press |
| ECMA | Econometrica | 0012-9682 | Econometric Society / Wiley |

The goals that distinguish EconPub do not change: coauthor-network topology,
career stage at publication, explicit provenance and confidence, and visible
missingness. Expanding the journal set increases the value of the first two —
a cross-journal coauthor network is far more informative than five separate
single-journal graphs — while increasing the scale and the validation burden.

## Scale estimate

Crossref reports the following record counts for 2000–present (queried
2026-10-26, `rows=0`):

| Journal | Crossref records 2000–present |
|---|---|
| AER | 5,498 |
| QJE | 1,368 |
| JPE | 2,143 |
| RES | 1,832 |
| ECMA | 2,602 |
| **Total** | **13,443** |

These include book reviews, comments, editorials, and other non-research
items, so the research-article count will be lower. The author-slot count is
likely roughly 2.5–3× the current AER corpus; the exact figure depends on
article classification and byline parsing.

## Why this is a planned milestone, not a config change

The existing pipeline is AER-specific in several places:

- `config.py` hard-codes one journal name and ISSN.
- AEA issue pages supply the article calendar and some byline detail; QJE, JPE,
  RES, and Econometrica do not use the AEA platform.
- The article-type classifier is tuned to AER's sections (Articles, Shorter
  Papers, Papers & Proceedings, Comments and Replies).
- The API and frontend assume one journal in overview, filters, and labels.
- Career coverage is reported against AER slots only.

A journal is therefore a first-class dimension of the data model, not a filter
applied after ingestion.

## M7.1 status (2026-10-26)

The multi-journal data foundation is in progress:

- A journal registry (`config.JOURNALS`) now holds the five codes, names, and
  print ISSNs. `harvest --journal {AER,QJE,JPE,RES,ECMA}` selects one.
- `papers.journal_code` is part of the schema, backfilled to `AER` for the
  existing database, and indexed with `(journal_code, published_year)`.
- Crossref page caches are namespaced per journal (`data/raw/crossref/pages/QJE/`).
- The classifier now separates generic rules (issue metadata, errata,
  announcements, editorial board/table-of-contents pages, duplicates) from
  AER-only section conventions (P&P, AEA reports, AEA front matter). AER output
  is unchanged; the AER-only SQL is gated by `journal_code`.
- A QJE pilot (separate database, not merged into the public AER corpus)
  ingested all **1,368** Crossref records for 2000–2026: **1,181** research
  articles, **55** duplicate deposits, **10** errata, **81** front-matter
  items, **35** issue records, **3,085** author slots, and **609** records with
  a Crossref abstract. The remaining two journals' section conventions — book
  reviews in JPE/RES and comments/notes in all three — still need inspection
  before their pilots are considered clean.

## Phases

### M7.1 — Multi-journal data foundation

1. Replace the single-journal constants with a journal registry (code, name,
   ISSN print/online, publisher, Crossref prefix, platform).
2. Harvest Crossref by ISSN for 2000–present, preserving raw source records.
3. Classify research articles, P&P/short papers, comments/replies, book
   reviews, editorials, and corrigenda **per journal**. Validate the classifier
   against a manually coded sample from each journal; publish the sample and
   the error rate.
4. Deduplicate across journals and against the existing AER corpus. Add a
   `journal_code` column and `(journal_code, published_year)` index.
5. Produce an M1-style audit for each new journal: record counts, date
   coverage, author-slot counts, abstract and affiliation coverage, and a
   list of classification edge cases.

Acceptance: each journal has a reproducible ingest, a documented article-type
rule set, and an audit report; no journal is silently mixed into AER totals.

### M7.2 — Identity and enrichment across journals

1. Run OpenAlex DOI-keyed enrichment for all journals (the layer is already
   journal-agnostic).
2. Re-run ORCID identity matching with the larger corpus. A new paper is
   additional evidence, so some previously unverified ORCID links may become
   verifiable — and some new false positives may appear. Re-run the rejection
   rules and report the change.
3. Reconcile author identities across journals: the same person must share one
   `stable_id`. Review cross-journal merges and splits with the existing ledger.
4. Rebuild the coauthorship graph with journal and year attributes on edges.

Acceptance: cross-journal stable IDs are reviewed; identity precision is not
worse than the AER-only layer; the network is queryable by journal and year.

### M7.3 — Career layer at the new scale

1. Extend ORCID/CV coverage to authors who appear only in the new journals.
2. Prioritize authors with many papers and low existing coverage; keep the
   current evidence hierarchy (byline > ORCID > historical web > CV > heuristic).
3. Use Common Crawl as the historical-page source where the Internet Archive
   is unreachable. Record it as its own provenance, not as Wayback.
4. Report career coverage **per journal and per year**, not only in aggregate.

Acceptance: coverage is measured and documented for every journal; missingness
remains explicit; no imputation is introduced to make the numbers look better.

### M7.4 — API and frontend

1. Add `journal` to paper, author, overview, and network responses.
2. Add journal filters to paper search, author lists, and the network explorer;
   keep "all journals" as an explicit option.
3. Show per-journal coverage in the overview and methodology pages.
4. Re-check pagination, query plans, and network bounds at roughly five times
   the current data volume.

Acceptance: no endpoint serializes the full database; every view states which
journals it covers.

### M7.5 — Validation and release

1. Per-journal spot checks of article types, authorship order, and dates.
2. Cross-journal identity spot checks, especially common names.
3. Regenerate all reports; version the release and keep the AER-only snapshot
   reproducible.
4. Update `docs/methodology.md`, `docs/data-sources.md`, and the README scope.

## Risks and controls

| Risk | Control |
|---|---|
| Article-type misclassification differs by journal | Manual sample per journal; publish error rates; keep ambiguous types out of research-article counts |
| Crossref metadata quality varies (abstracts, affiliations) | Report coverage by journal; use OpenAlex/ publisher pages only as documented supplements |
| Cross-journal author merges create false identities | Existing ledger and review queue; conservative merge rules; visible uncertainty |
| Scale makes the crawl and API slow | Resumable harvests, indexes, bounded pages, explicit truncation reporting |
| Coverage look better in aggregate but worse in a journal | Per-journal reporting; no pooled headline without the breakdown |
| Historical-web evidence is weaker than byline/ORCID | Keep the evidence hierarchy and confidence caps; never promote archive evidence above explicit sources |

## Explicit non-goals

- Full-text redistribution of any journal.
- Pre-2000 coverage in this phase.
- Treating the five journals as a ranking of all economics output.
- Auto-publishing unreviewed corrections or inferred career stages.
