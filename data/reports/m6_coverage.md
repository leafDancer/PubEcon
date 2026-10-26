# M6 Coverage Report — AER 2000+

Generated: 2026-10-25T07:45:41+00:00

M6 measures the yield of the CV/homepage crawl and historical-page snapshots. It is a provenance report, not a claim that every public CV has been found.

## CV crawl

| Metric | Value |
|---|---|
| CV/homepage sources | 1362 |
|   — candidates | 0 |
|   — homepages parsed | 633 |
|   — documents downloaded | 294 |
|   — documents parsed | 268 |
|   — name mismatches | 19 |
|   — failed | 442 |
| Authors with CV events | 187 |
| CV career events | 1129 |
| CV career assignments | 45 |

| Source status | Sources |
|---|---|
| homepage_fetched | 633 |
| failed | 442 |
| parsed | 268 |
| name_mismatch | 19 |

| Source type | Status | Sources |
|---|---|---|
| orcid_researcher_url | homepage_fetched | 633 |
| orcid_researcher_url | failed | 370 |
| cv_link | parsed | 267 |
| cv_link | failed | 72 |
| cv_link | name_mismatch | 19 |
| cv_document | parsed | 1 |

## CV yield by domain

| Domain | Parsed | Failed / mismatch | Other |
|---|---|---|---|
| voices.uchicago.edu | 4 | 0 | 0 |
| sites.northwestern.edu | 4 | 0 | 0 |
| www.econ.uzh.ch | 3 | 0 | 0 |
| personal.lse.ac.uk | 3 | 0 | 0 |
| 192.218.163.164 | 3 | 0 | 0 |
| lantpritchett.org | 3 | 0 | 0 |
| web.sas.upenn.edu | 2 | 0 | 0 |
| dalumat.ai | 2 | 0 | 0 |
| www.bsfrey.ch | 2 | 0 | 0 |
| sites.bu.edu | 2 | 0 | 0 |
| www.susannaberkouwer.com | 2 | 0 | 0 |
| blog.iese.edu | 2 | 0 | 0 |
| fportier.wordpress.com | 2 | 0 | 0 |
| www.david-anthoff.com | 2 | 0 | 0 |
| eml.berkeley.edu | 2 | 0 | 0 |

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
