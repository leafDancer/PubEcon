# M6 Coverage Report — AER 2000+

Generated: 2026-10-25T04:12:44+00:00

M6 measures the yield of the CV/homepage crawl and historical-page snapshots. It is a provenance report, not a claim that every public CV has been found.

## CV crawl

| Metric | Value |
|---|---|
| CV/homepage sources | 1347 |
|   — candidates | 70 |
|   — homepages parsed | 626 |
|   — documents downloaded | 281 |
|   — documents parsed | 256 |
|   — name mismatches | 18 |
|   — failed | 377 |
| Authors with CV events | 177 |
| CV career events | 1069 |
| CV career assignments | 43 |

| Source status | Sources |
|---|---|
| homepage_fetched | 626 |
| failed | 377 |
| parsed | 256 |
| candidate | 70 |
| name_mismatch | 18 |

| Source type | Status | Sources |
|---|---|---|
| orcid_researcher_url | homepage_fetched | 626 |
| orcid_researcher_url | failed | 377 |
| cv_link | parsed | 255 |
| cv_link | candidate | 70 |
| cv_link | name_mismatch | 18 |
| cv_document | parsed | 1 |

## CV yield by domain

| Domain | Parsed | Failed / mismatch | Other |
|---|---|---|---|
| voices.uchicago.edu | 4 | 0 | 0 |
| www.econ.uzh.ch | 3 | 0 | 0 |
| lantpritchett.org | 3 | 0 | 0 |
| sites.google.com | 2 | 0 | 0 |
| dalumat.ai | 2 | 0 | 0 |
| www.bsfrey.ch | 2 | 0 | 0 |
| sites.bu.edu | 2 | 0 | 0 |
| www.susannaberkouwer.com | 2 | 0 | 0 |
| blog.iese.edu | 2 | 0 | 0 |
| www.david-anthoff.com | 2 | 0 | 0 |
| personal.lse.ac.uk | 2 | 0 | 0 |
| eml.berkeley.edu | 2 | 0 | 0 |
| sites.northwestern.edu | 2 | 0 | 0 |
| koichiroito.com | 2 | 0 | 0 |
| www.tax.mpg.de | 2 | 0 | 0 |

## Historical pages (Wayback)

| Metric | Value |
|---|---|
| Archived snapshots | 0 |
|   — candidates | 0 |
|   — fetched | 0 |
|   — parsed | 0 |
|   — failed | 0 |
|   — empty | 0 |
| Wayback career events | 0 |
| Wayback career assignments | 0 |

## Interpretation

- A parsed document may contain zero usable events; the parser is conservative. `candidate` rows are the resumable queue, not missing data.
- Failed and name-mismatch sources remain in the table for audit. They are not silently retried forever; `--retry-failed` requeues them.
- Wayback snapshots are tied to one paper year. They are used only when an academic rank appears near the author's name, and confidence is capped at medium.
- The Internet Archive was not reachable from the development network used for this run; see `docs/m6-coverage.md`.
