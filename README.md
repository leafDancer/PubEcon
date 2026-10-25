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
- **Status:** M5 frontend MVP complete — Crossref metadata classified and deduplicated; AEA issue calendar and OpenAlex enrichment done; stable author IDs and identity review in place; ORCID career timelines validated against AER evidence; a read-only API and React frontend now serve paper, author, career-timeline, network, and methodology views. The AEA JEL crawl and full CV corpus remain resumable.
- **Not included:** pre-2000 archive, full text, or personal data such as birth dates, addresses, and emails

## Architecture

The browser never downloads the database. A read-only FastAPI service exposes paginated paper and author views plus bounded network subgraphs; a React/Vite frontend consumes only those endpoints.

```
React (web/)  ->  FastAPI /api (src/econpub/api.py)  ->  SQLite mode=ro
```

The API caps page sizes and never serializes all 5,892 authors or 9,375 coauthorship edges. Network views are explicit ranked samples, and the response reports what was truncated. See `docs/m5-frontend.md` for routes, endpoints, design tokens, and deployment notes.

## Current dataset (M4)

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
| Authors flagged for review | 1,459 (905 unverified ORCID, 292 field-low, 249 rejected, 28 OpenAlex; overlaps) |
| Authors with OpenAlex ID | 5,526 |
| Authors with ORCID | 3,314 (56.2%) |
|   — accepted identity evidence | 2,409 |
|   — unverified (events withheld) | 905 |
|   — rejected identity | 249 |
| ORCID identities contributing events | 2,067 |
| ORCID career events | 5,847 (4,583 dated) |
| CV/homepage sources discovered | 1,088 |
| CV documents parsed (pilot) | 17 |
| Coauthorship edges | 9,375 |
| Career assignments (all sources) | 2,264 (21.0% of slots) |
|   — byline | 669 |
|   — ORCID | 1,591 |
|   — CV pilot | 4 |
|   — high/medium confidence | 1,349 |
|   — low confidence | 915 |
| Publish-time byline coverage | 99.8% |
| Resolved institution (OpenAlex) coverage | 94.5% |
| Any rank/title mention | 6.2% |
| Explicit academic rank coverage | 0.3% |
| Abstract coverage | 89.9% (boilerplate filtered) |
| OpenAlex work coverage | 98.9% |
| JEL coverage | 14.6% and rising (AEA crawl resumable) |
| Duplicate records excluded | 67 |
| Retraction notices / retracted originals | 2 / 2 |

The M2/M3/M4 reports are in `data/reports/m2_quality.md`, `m3_quality.md`, and `m4_quality.md`. The M1 independent audit and its full evidence are in `docs/audit-m1.md` and `docs/audit-m1-findings.json`. The API and frontend are documented in `docs/m5-frontend.md`.

Three findings shape the next milestones:

1. **ORCID is the highest-yield career source, but only after identity validation.** 3,314 authors retain an ORCID; 2,409 have direct evidence (matching AER DOI/title or institution) or a conservative economics-field signal, and 905 are unverified links whose events are withheld. 2,067 accepted identities contribute 5,847 events and raise career coverage from 6.2% (byline only) to 21.0% (2,264 assignments). Generic "Professor" titles are stored as full professor with **low confidence** because the title may be current rather than the rank at the paper date; explicit ranks are high confidence.
2. **Stable identity needs explicit reconciliation.** The 40 multi-OpenAlex-ID authors were reviewed: 3 were confirmed resolver over-merges and split (John W./M. Morgan, Benjamin I./R. Page, Daniel G./M. Sullivan), 32 are OpenAlex duplicate profiles, and 5 remain uncertain. 28 authors carry OpenAlex fragmentation flags. ORCID identity validation rejects 72 person-name conflicts, 165 clear field mismatches, and 12 career-changing links without positive evidence.
3. **CVs are the next coverage frontier.** ORCID researcher URLs yielded 1,088 public CV/homepage sources. The pilot parsed 17 CVs and extracted 60 dated events, but discovery and parsing are deliberately conservative. The full CV corpus is a resumable crawl, not an automatic claim of complete coverage.

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

Then run the identity and career passes:

```powershell
python run.py m3
python run.py m4
```

M3 assigns stable author IDs, resolves the seven namesake candidates, reviews the 40 authors with multiple OpenAlex IDs (splitting three confirmed over-merges), writes permanent separation rules, and produces byline career assignments. M4 adds ORCID employment/education timelines, validates each ORCID link against AER evidence before using its events, and infers career stages at publication. The reports are `data/reports/m3_quality.md` and `data/reports/m4_quality.md`.

The CV layer is a separate, resumable crawl:

```powershell
python run.py cvs --limit 300
```

It seeds from ORCID researcher URLs, discovers CV links, stores raw documents only in the local ignored cache, extracts dated events, and uses them only where byline/ORCID evidence is absent.

### Run the public interface

The frontend and API are separate processes. Install the API extra once:

```powershell
pip install -e ".[api]"
```

In one terminal:

```powershell
python run.py serve --port 8000
```

In another:

```powershell
cd web
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to the FastAPI service. For a separated deployment, set `VITE_API_BASE` at frontend build time and `ECONPUB_CORS_ORIGINS` on the API; see `docs/m5-frontend.md`.

Useful commands:

```powershell
python run.py harvest --resume   # reuse cached Crossref pages
python run.py harvest --refresh  # re-fetch with the current field selection
python run.py aea --workers 1 --delay 1.0   # resume the cached AEA crawl
python run.py openalex          # reuse cached OpenAlex batches
python run.py pages             # expand abbreviated page ranges
python run.py calendar          # apply the AEA issue-month calendar
python run.py m3                # rebuild identity review and byline careers
python run.py m4                # fetch ORCID timelines, validate identities, assign careers
python run.py m4 --skip-orcid   # revalidate cached ORCID links without network
python run.py cvs --limit 300   # expand CV discovery/parsing
python run.py serve             # run the read-only JSON API on port 8000
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
  career.py        byline, ORCID, and CV career-stage assignments
  orcid.py         ORCID record harvest and employment/education events
  cv.py            CV/homepage discovery and conservative CV parsing
  pages.py         abbreviated page-range expansion and validation
  quality.py       coverage, provenance, and M2-M4 reports
  api.py           read-only FastAPI service for the public frontend
  cli.py           command-line entry point
  schema.sql       database schema
web/
  src/             React routes, components, charts, and network explorer
  public/          static assets
  scripts/         build helpers (SPA 404 fallback)
docs/
  methodology.md   public methodology and inference rules
  data-sources.md  source reconnaissance and known limitations
  m4-validation.md  concrete ORCID/CV spot checks and parser fixes
  m5-frontend.md   API surface, frontend routes, design system, deployment
  audit-m1.md      independent multi-agent audit and remediation status
tests/
  test_normalize.py
  test_classify.py
  test_m2.py
  test_m3.py
  test_m4.py
  test_api.py
```

## Data model

The core tables are `papers`, `authorships`, `authors`, `author_aliases`, `author_merge_candidates`, `author_openalex_evidence`, `author_split_candidates`, `author_identity_ledger`, `author_identity_events`, `author_separation_rules`, `institutions`, `authorship_institutions`, `paper_topics`, and `source_records`. `coauthorship_edges` is built from canonical authorships. `career_events` stores dated education/employment facts from ORCID and CVs; `career_assignments` stores the inferred stage at each publication with evidence type, confidence, and source URL. `author_cv_sources` records public CV/homepage provenance; raw documents are kept only in the ignored local cache.

`papers.content_type` separates research articles from front matter, issue metadata, unattributed records, errata, AEA association reports/minutes, retraction notices, and duplicates. Only research articles feed the publication and network statistics; P&P articles are research articles with `is_pp = 1`. Retracted originals stay in `article` with a `retraction_status` flag and a pointer to the notice. Crossref `update-to` is the primary retraction link, with an explicit fallback pair list.

Author resolution is rebuildable: `authors.py` groups authorships by a middle-initial-, particle-, and Unicode-aware key, merges safe variants, splits known namesakes, and writes uncertain pairs to `author_merge_candidates`. `openalex.py` attaches OpenAlex author IDs, records every observed ID in `author_openalex_evidence`, and merges only pairs that OpenAlex says are the same person and whose names are compatible.

`papers.abstract_source` and `papers.date_source` record provenance. `paper_topics` uses separate schemes for author-assigned JEL codes and machine-generated OpenAlex topics. `institutions` and `authorship_institutions` store resolved entities and multiple publish-time affiliations per authorship.

`career_assignments` is the key table for the project's distinctive claim: each row records a publish-time stage, the evidence type, a confidence level, and a source URL. `authors.orcid_source` records the identity tier (`verified_doi`, `verified_title`, `verified_institution`, `field_economics`, `orcid_unverified`) or rejection reason; only accepted tiers contribute ORCID events.

`api.py` opens the database read-only and serves bounded JSON views. The React frontend never receives raw tables; paper and author indexes are paginated, and network views are ranked subgraphs with explicit truncation metadata.

## Roadmap

- **M1** — schema, Crossref harvest, content classification, deduplication, canonical authors, quality report ✅
- **M2** — AEA JEL/abstract enrichment; OpenAlex DOI-keyed enrichment, author IDs, institutions, topics; fix 2002–2009 issue-month mapping; page-range validation ✅
- **M3** — stable author IDs and identity ledger; resolve the 7 merge candidates and 40 multi-OpenAlex-ID authors; split confirmed over-merges; byline-only career assignments ✅
- **M4** — ORCID employment/education timelines; conservative CV discovery and parsing; career assignments with evidence and confidence ✅ (CV corpus remains resumable)
- **M5** — read-only FastAPI service and React frontend: paper pages, author pages, career timelines, coauthor network explorer, methodology page, and a bounded network API ✅ (deployment and corpus expansion remain)

## Data ethics

- Only bibliographic metadata and short excerpts are stored; no full text.
- CV-derived data is limited to structured degree/employment facts with a source URL.
- Missing data is shown as missing, not silently imputed.
- A takedown/correction process will be added before public launch.

## License

To be decided before public release. Code and data may need different licenses because the underlying sources have different terms.
