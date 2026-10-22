# EconPub

An open, methodologically documented database of publications in the *American Economic Review* (AER), with a coauthor network and publish-time career-stage inference.

## Why this exists

Existing economics publication sites are strong on citation counts and journal rankings, but weak on two questions that matter for understanding how the field works:

1. **Who worked with whom, and how did those networks evolve?**
2. **What was each author's career stage when the paper was published?**

EconPub makes both first-class. Every inferred field carries its evidence and confidence, so the result is inspectable rather than a black box.

## Scope (v0.1)

- **Journal:** American Economic Review (ISSN 0002-8282)
- **Years:** 2000–present
- **Status:** M3 complete — Crossref metadata classified and deduplicated; AEA issue calendar and OpenAlex enrichment done; stable author IDs, author-identity review, and byline-only career assignments added; the AEA JEL crawl is partial and resumable; CV career timelines and frontend follow
- **Not included:** pre-2000 archive, full text, or personal data such as birth dates, addresses, and emails

## Current dataset (M3)

| Metric | Value |
|---|---|
| Crossref records | 5,498 |
| Research articles (incl. P&P) | 4,786 |
| P&P articles (2000–2017) | 1,795 |
| Author slots | 10,782 |
| Canonical authors | 5,892 |
| Authors with stable IDs | 5,892 |
| Author aliases | 6,382 |
| Pending merge candidates | 0 |
| Resolved split candidates | 7 |
| Confirmed author splits | 3 |
| Multi-ID fragmentation reviewed | 32 authors |
| Multi-ID uncertain (flagged) | 5 authors |
| Authors flagged for review | 45 |
| Authors with OpenAlex ID | 5,526 |
| Coauthorship edges | 9,375 |
| Career assignments (byline-only) | 669 (6.2% of slots) |
| Publish-time byline coverage | 99.8% |
| Resolved institution (OpenAlex) coverage | 94.5% |
| Any rank/title mention | 6.2% |
| Explicit academic rank coverage | 0.3% |
| Abstract coverage | 89.9% (boilerplate filtered) |
| OpenAlex work coverage | 98.9% |
| JEL coverage | 14.6% and rising (AEA crawl resumable) |
| Duplicate records excluded | 67 |
| Retraction notices / retracted originals | 2 / 2 |

The full M2 and M3 reports are in `data/reports/m2_quality.md` and `data/reports/m3_quality.md`. The M1 independent audit and its full evidence are in `docs/audit-m1.md` and `docs/audit-m1-findings.json`.

Three findings shape the next milestones:

1. **Byline rank is not enough.** Only about 0.3% of author slots carry an explicit academic rank such as "Assistant Professor"; the 6.2% "any title" figure is almost entirely non-academic affiliations. The M3 byline-only career layer covers 669 slots (6.2%) and leaves 10,113 unknown; CV timelines are essential for the rest.
2. **Stable identity needs explicit reconciliation.** The 40 multi-OpenAlex-ID authors were reviewed: 3 were confirmed resolver over-merges and split (John W./M. Morgan, Benjamin I./R. Page, Daniel G./M. Sullivan), 32 are OpenAlex duplicate profiles, and 5 remain uncertain. Stable IDs and permanent separation rules ensure confirmed splits survive future rebuilds.
3. **Dates need a source hierarchy.** Crossref and OpenAlex both report 2002–2009 issue months one month early. The database uses the AEA all-issues calendar and article pages for all article months; Crossref issue metadata and the AER five-issue calendar remain only as offline fallbacks.

## Data sources

| Source | Role |
|---|---|
| Crossref REST API | Primary article metadata and publish-time affiliation strings |
| AEA article pages | JEL classification, abstracts, publication details |
| OpenAlex | DOI-keyed enrichment: author IDs, citation counts, topics |
| Author CVs and faculty pages | Education and employment timelines for career-stage inference |

OpenAlex is never used as the primary record. Its author affiliation history mixes in coauthor institutions, and its historical publication years contain known errors. See `docs/data-sources.md` for the reconnaissance evidence.

## Quick start

```powershell
python run.py all
```

This creates:

- `data/curated/econpub.db` — SQLite database
- `data/raw/crossref/pages/` — verbatim API pages for auditing and resume
- `data/reports/m1_quality.md` and `m1_quality.json` — M1 coverage and quality report

After the M1 pipeline, run the enrichment pass:

```powershell
python run.py m2 --workers 1 --delay 1.0
```

This fixes issue months, crawls AEA article pages for JEL/abstracts, enriches with OpenAlex, links authors, and writes `data/reports/m2_quality.md`.

Then run the identity and career pass:

```powershell
python run.py m3
```

This assigns stable author IDs, resolves the seven namesake candidates, reviews the 40 authors with multiple OpenAlex IDs (splitting three confirmed over-merges), writes permanent separation rules, and produces byline-only career assignments in `data/reports/m3_quality.md`.

Useful commands:

```powershell
python run.py harvest --resume   # reuse cached Crossref pages
python run.py harvest --refresh  # re-fetch with the current field selection
python run.py aea --workers 1 --delay 1.0   # resume the cached AEA crawl
python run.py openalex          # reuse cached OpenAlex batches
python run.py pages             # expand abbreviated page ranges
python run.py calendar          # apply the AEA issue-month calendar
python run.py m3                # rebuild identity review and byline careers
python run.py report            # regenerate the report without rebuilding authors
python -m unittest discover -s tests -v
```

`report` is read-only with respect to the author layer. Rebuilding authors is done by `harvest`/`all`; stable IDs and separation rules survive, but rerun `m2`/`m3` to refresh OpenAlex links and review labels.

Set a contact address for Crossref's polite pool:

```powershell
$env:ECONPUB_MAILTO="you@example.com"
```

## Project layout

```
src/econpub/
  config.py        paths, journal constants, API settings
  normalize.py     text/date/name/rank/page normalization
  db.py            SQLite schema and upserts
  crossref.py      paginated Crossref harvest
  classify.py      content types, P&P, retractions, deduplication
  authors.py       canonical author resolution and coauthorship edges
  aea.py           AEA article-page crawl: JEL, abstracts, issue months
  openalex.py      DOI-keyed OpenAlex work/author/institution enrichment
  identity.py      stable author IDs, ledger, and identity events
  review.py        merge-candidate resolution, multi-ID review, author splits
  career.py        conservative byline-only career assignments
  pages.py         abbreviated page-range expansion and validation
  quality.py       coverage, provenance, and M3 identity/career reports
  cli.py           command-line entry point
  schema.sql       database schema
docs/
  methodology.md   public methodology and inference rules
  data-sources.md  source reconnaissance and known limitations
  audit-m1.md      independent multi-agent audit and remediation status
tests/
  test_normalize.py
  test_classify.py
  test_m2.py
  test_m3.py
```

## Data model

The core tables are `papers`, `authorships`, `authors`, `author_aliases`, `author_merge_candidates`, `author_openalex_evidence`, `author_split_candidates`, `author_identity_ledger`, `author_identity_events`, `author_separation_rules`, `institutions`, `authorship_institutions`, `paper_topics`, and `source_records`. `coauthorship_edges` is built from canonical authorships. `career_assignments` is populated by M3 for byline-documented stages; `career_events` remains reserved for the CV timeline layer.

`papers.content_type` separates research articles from front matter, issue metadata, unattributed records, errata, AEA association reports/minutes, retraction notices, and duplicates. Only research articles feed the publication and network statistics; P&P articles are research articles with `is_pp = 1`. Retracted originals stay in `article` with a `retraction_status` flag and a pointer to the notice. Crossref `update-to` is the primary retraction link, with an explicit fallback pair list.

Author resolution is rebuildable: `authors.py` groups authorships by a middle-initial-, particle-, and Unicode-aware key, merges safe variants, splits known namesakes, and writes uncertain pairs to `author_merge_candidates`. `openalex.py` attaches OpenAlex author IDs, records every observed ID in `author_openalex_evidence`, and merges only pairs that OpenAlex says are the same person and whose names are compatible.

`papers.abstract_source` and `papers.date_source` record provenance. `paper_topics` uses separate schemes for author-assigned JEL codes and machine-generated OpenAlex topics. `institutions` and `authorship_institutions` store resolved entities and multiple publish-time affiliations per authorship.

`career_assignments` is the key table for the project's distinctive claim: each row records a publish-time stage, the evidence type, a confidence level, and a source URL.

## Roadmap

- **M1** — schema, Crossref harvest, content classification, deduplication, canonical authors, quality report ✅
- **M2** — AEA JEL/abstract enrichment; OpenAlex DOI-keyed enrichment, author IDs, institutions, topics; fix 2002–2009 issue-month mapping; page-range validation ✅
- **M3** — stable author IDs and identity ledger; resolve the 7 merge candidates and 40 multi-OpenAlex-ID authors; split confirmed over-merges; byline-only career assignments ✅
- **M4** — tiered CV corpus and timeline extraction; extend career assignments beyond byline-documented slots
- **M5** — static frontend (paper pages, author pages, network explorer, methodology page)

## Data ethics

- Only bibliographic metadata and short excerpts are stored; no full text.
- CV-derived data is limited to structured degree/employment facts with a source URL.
- Missing data is shown as missing, not silently imputed.
- A takedown/correction process will be added before public launch.

## License

To be decided before public release. Code and data may need different licenses because the underlying sources have different terms.
