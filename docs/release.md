# Release checklist

- Repository: <https://github.com/leafDancer/PubEcon>
- Release page: <https://github.com/leafDancer/PubEcon/releases/tag/v1.0.0>

## v1.0.0 (code and data)

- Package version: `1.0.0` (`pyproject.toml`, `src/econpub/__init__.py`,
  `web/package.json`).
- Dataset: `data/curated/top5.db`, built from the cached Crossref/OpenAlex/ORCID
  sources. It is not tracked in git; publish it as a release asset.
- Manifest: run `python run.py release-manifest --db data/curated/top5.db` and
  publish `data/reports/release_manifest.md` and `.json` with the asset. The
  manifest records the database byte size, SHA-256, counts, per-journal totals,
  raw-cache inventory, and report hashes.
- Verification:

  ```powershell
  Get-FileHash data/curated/top5.db -Algorithm SHA256
  python -m unittest discover -s tests -v
  cd web
  npm ci
  npm run build
  ```

- The full API integration tests require the curated databases; on a fresh
  clone they skip. `tests/test_top5.py` runs against `top5.db` when present.

## Release decisions

1. **License.** Resolved: MIT for code (`LICENSE`) and CC BY 4.0 for the
   PubEcon compilation (`DATA_LICENSE.md`). Third-party metadata and abstracts
   remain subject to their source terms.
2. **Correction channel.** Resolved: public GitHub Issues with the
   `.github/ISSUE_TEMPLATE/correction.yml` template and the process in
   `docs/corrections.md`.
3. **Deployment.** The API and static frontend have not been deployed together
   from this repository. Set `PUBECON_DB`, `PUBECON_CORS_ORIGINS`, and
   `VITE_API_BASE` as described in `docs/m5-frontend.md`.
4. **Validation limits.** A targeted 12-per-journal article-type sample was
   inspected; per-journal error rates are not estimated. Author identity beyond
   the reviewed namesake cases remains a review-queue risk, not a precision
   claim.

## Tagging

After the database artifact is uploaded and the repository's Issues tracker is
public:

```powershell
git tag -a v1.0.0 -m "PubEcon v1.0.0"
git push origin v1.0.0
```

Do not describe the hosted service as publicly launched until deployment and
the release-asset upload are complete.
