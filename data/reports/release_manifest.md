# Release manifest

- **Product:** PubEcon
- **Version:** 1.0.0
- **Generated:** 2026-10-26T15:56:11+00:00
- **Git commit:** 08fc100bbe8a1fa2b991359be9b82c04dc702375
- **Database:** `data\curated\top5.db`
- **Database bytes:** 549,416,960
- **Database SHA-256:** `cdedad2fd7f231ef6a1c037e7e3bdf7f9d55dc7437574bf407088e4bc626569e`

## Headline counts

| Metric | Value |
|---|---:|
| Crossref records | 13,443 |
| Research articles | 10,957 |
| Author slots | 25,205 |
| Active canonical authors | 10,042 |
| Coauthor ties (unique pairs) | 19,728 |
| Coauthor edge records | 24,108 |
| Career assignments | 4,961 |

## Journals

| Journal | Articles | Author slots | Career assignments |
|---|---:|---:|---:|
| AER — American Economic Review | 4,787 | 10,786 | 2,316 |
| RES — Review of Economic Studies | 1,749 | 4,037 | 845 |
| ECMA — Econometrica | 1,740 | 3,820 | 668 |
| JPE — Journal of Political Economy | 1,500 | 3,477 | 636 |
| QJE — Quarterly Journal of Economics | 1,181 | 3,085 | 496 |

## Reproducibility notes

- Raw source cache: `D:\Research\econ-pub-database\data\raw` (10,416 files, 946,112,311 bytes). It is not included in this manifest hash; the cached Crossref/OpenAlex/ORCID payloads are the audit trail for a rebuild.
- The database is the authoritative release artifact. Rebuilding from live APIs can produce a different snapshot even with the same code.
- Publish the database as a release asset and keep this manifest with it; verify with `sha256sum` (Linux/macOS) or `Get-FileHash` (PowerShell).
