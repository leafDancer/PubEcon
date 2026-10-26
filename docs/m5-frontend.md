# M5 frontend and API

M5 separates the public interface from the database. The browser never downloads the SQLite file and never receives the full author or coauthorship table.

```
Browser
  React + Vite (web/)
        |
        |  GET /api/...
        v
  FastAPI read-only service (src/econpub/api.py)
        |
        |  SQLite mode=ro
        v
  data/curated/econpub.db
```

The API is read-only. It opens the database with `mode=ro`, sets `PRAGMA query_only=ON`, and exposes paginated or bounded views. The frontend uses URL parameters for shareable filters and pages.

## Running locally

Two terminals:

```powershell
python run.py serve --port 8000
```

```powershell
cd web
npm install
npm run dev
```

The Vite dev server runs at `http://127.0.0.1:5173` and proxies `/api` to `http://127.0.0.1:8000`. No frontend build is needed during development.

For a separated deployment, set `VITE_API_BASE` at build time:

```powershell
$env:VITE_API_BASE="https://api.example.org/api"
npm run build
```

On the API side, allow the frontend origin:

```powershell
$env:ECONPUB_CORS_ORIGINS="https://econpub.example.org"
$env:ECONPUB_DB="D:\data	op5.db"
uvicorn econpub.api:app --host 0.0.0.0 --port 8000
```

## API surface

| Route | Purpose |
|---|---|
| `GET /api/health` | Liveness and database path |
| `GET /api/overview` | Landing-page counts, per-journal inventory and coverage, yearly series, stages, institutions, recent and most-cited papers |
| `GET /api/stats` | Same statistical payload without the landing-page framing |
| `GET /api/papers` | Paginated paper index; filters `q`, `journal`, `year_from`, `year_to`, `is_pp`, `sort` |
| `GET /api/papers/{doi}` | Paper detail: authorships, career assignments, institutions, JEL, OpenAlex topics, provenance |
| `GET /api/authors` | Paginated author index; filters `q`, `stage`, `year_from`, `year_to`, `sort` |
| `GET /api/authors/{stable_id}` | Author profile, career events, per-paper assignments, coauthors, institutions |
| `GET /api/authors/{stable_id}/network` | Bounded ego network (default 50 coauthors, max 150); optional `journal` filter |
| `GET /api/network` | Ranked subgraph: top authors by papers in a year range, bounded to 600 nodes; optional `journal` filter |
| `GET /api/network/stats` | Cached average path length, diameter, components, and clustering for `ALL` or one journal |
| `GET /api/rankings` | Bounded leaderboards: assistant-professor output, five-journal authors, most coauthors, strongest pairs, largest teams, longest careers, and institutions |
| `GET /api/path` | Shortest coauthorship path between two stable IDs (`from`, `to`), with the shared papers at each step |

Pagination is capped at 100 rows. The network endpoint is always a filtered sample; it never serializes all 5,892 authors or 9,375 edges. The response includes `meta.truncated` and `meta.total_authors` so the UI can say what is missing.

## Frontend routes

| Route | View |
|---|---|
| `/` | Overview: year ruler, summary counts, career-stage mix, network sample, recent and most-cited papers |
| `/papers` | Searchable, filterable paper index |
| `/papers/{doi}` | Paper page with abstract, byline, career-at-publication table, JEL, topics, citations |
| `/authors` | Searchable author index with stage and coverage filters |
| `/authors/{stable_id}` | Author page with career timeline, papers, evidence, coauthors, institutions |
| `/network` | Coauthor explorer; supports `?focus=<stable_id>` for an ego network and `?journal=` for a journal-scoped graph; shows cached graph statistics |
| `/connection` | Shortest-path finder between two authors, with per-step paper evidence |
| `/methodology` | Public method, evidence hierarchy, ORCID identity tiers, and limitations |

## Design system

The interface is a research ledger, not a dashboard of cards:

- **Palette:** cool archival paper `#ECEFEA`, sheet `#FAFAF6`, pine ink `#15201B`, primary green `#214F3F`, ochre `#B9872C`, rust `#A34A3B`, cobalt `#2F5E86`. The three-step blue ramp (`#104281`, `#2A78D6`, `#86B6EF`) encodes career-evidence confidence; exact stage names are always printed, so colour is not the only channel.
- **Type:** Newsreader for editorial display, Archivo for UI, IBM Plex Mono for identifiers and data labels.
- **Layout:** a persistent left rail, a wide editorial hero, and ruled tables. The year ruler in the hero is the signature visual; the career timeline is the signature author view.
- **Accessibility:** visible focus, skip link, reduced-motion handling, chart tooltips plus table disclosures, and stage/confidence labels next to every colour mark.

## Deployment

- **Backend:** run `uvicorn econpub.api:app` behind a reverse proxy. The database is read-only and can be mounted on persistent storage. Set `ECONPUB_CORS_ORIGINS` to the frontend origin.
- **Database:** set `ECONPUB_DB` to the combined top-five database for the full product. If unset, the API uses `data/curated/top5.db` when present and otherwise falls back to the AER baseline.
- **Frontend:** `npm run build` produces `web/dist`. Serve it from any static host with SPA rewrites to `index.html`.
- **GitHub Pages:** `npm run build` also writes `dist/404.html` as a copy of the app shell. Set `VITE_BASE` to the repository path so asset URLs and the React Router basename match:

  ```powershell
  $env:VITE_BASE="/econpub/"
  $env:VITE_API_BASE="https://api.example.org/api"
  npm run build
  ```

  The generated `404.html` lets deep links reach the SPA; if the host does not support that fallback, use a host with rewrite rules.
- **API base:** set `VITE_API_BASE` to the public API prefix at build time.

## What remains

- The CV corpus is still a resumable crawl, not a complete corpus.
- The network explorer is a bounded ranked view. A future version can add server-side graph queries for larger windows, but the public UI should keep a bounded payload.
- The frontend has no authentication or write paths; corrections remain a separate editorial workflow.
