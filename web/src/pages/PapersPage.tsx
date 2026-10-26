import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import PaperRow from '../components/PaperRow'
import Pagination from '../components/Pagination'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { formatNumber, safeInt, useApi, useDebounced } from '../lib'

const YEARS = Array.from({ length: 27 }, (_, index) => 2000 + index)

export default function PapersPage() {
  const [params, setParams] = useSearchParams()
  const qParam = params.get('q') ?? ''
  const journal = params.get('journal') ?? 'all'
  const yearFrom = safeInt(params.get('year_from'), 2000, 2000, 2026)
  const yearTo = safeInt(params.get('year_to'), 2026, 2000, 2026)
  const pp = params.get('pp') ?? 'all'
  const sort = params.get('sort') ?? 'year_desc'
  const page = safeInt(params.get('page'), 1, 1)

  const [qInput, setQInput] = useState(qParam)
  const debouncedQ = useDebounced(qInput, 260)

  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [page])

  useEffect(() => {
    if (debouncedQ !== qParam) {
      update({ q: debouncedQ || null })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ])

  useEffect(() => {
    if (qParam !== qInput) setQInput(qParam)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qParam])

  function update(values: Record<string, string | number | null>) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(values)) {
      if (value === null || value === '') next.delete(key)
      else next.set(key, String(value))
    }
    if (!('page' in values)) next.delete('page')
    setParams(next, { replace: true })
  }

  const overview = useApi(() => api.overview(), [])
  const journalOptions = overview.data?.dataset.journals ?? []

  const isPp = pp === 'pp' ? true : pp === 'articles' ? false : undefined
  const listing = useApi(
    () =>
      api.papers({
        q: qParam,
        journal: journal === 'all' ? undefined : journal,
        year_from: yearFrom,
        year_to: yearTo,
        is_pp: isPp,
        sort,
        page,
        page_size: 25,
      }),
    [qParam, journal, yearFrom, yearTo, pp, sort, page],
  )

  return (
    <div className="ep-page">
      <header className="ep-page-head">
        <p className="ep-kicker">The record</p>
        <h1>Papers</h1>
        <p className="ep-page-deck">
          Research articles from the top five economics journals, 2000–2026, including AER
          Papers &amp; Proceedings through 2017.
        </p>
      </header>

      <section className="ep-filters" aria-label="Filter papers">
        <label className="ep-field ep-field-search">
          <span>Search titles, abstracts, authors</span>
          <input
            type="search"
            value={qInput}
            placeholder="e.g. minimum wage, Acemoglu, auction"
            onChange={(event) => setQInput(event.target.value)}
          />
        </label>
        {journalOptions.length > 1 && (
          <label className="ep-field">
            <span>Journal</span>
            <select
              value={journal}
              onChange={(event) =>
                update({
                  journal: event.target.value === 'all' ? null : event.target.value,
                  pp: 'all',
                })
              }
            >
              <option value="all">All five</option>
              {journalOptions.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.code} — {item.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="ep-field">
          <span>From</span>
          <select
            value={yearFrom}
            onChange={(event) => update({ year_from: Number(event.target.value) })}
          >
            {YEARS.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </select>
        </label>
        <label className="ep-field">
          <span>To</span>
          <select
            value={yearTo}
            onChange={(event) => update({ year_to: Number(event.target.value) })}
          >
            {YEARS.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </select>
        </label>
        {(journal === 'all' || journal === 'AER') && (
          <label className="ep-field">
            <span>Type</span>
            <select value={pp} onChange={(event) => update({ pp: event.target.value })}>
              <option value="all">All research</option>
              <option value="articles">Regular articles</option>
              <option value="pp">AER Papers &amp; Proceedings</option>
            </select>
          </label>
        )}
        <label className="ep-field">
          <span>Sort</span>
          <select value={sort} onChange={(event) => update({ sort: event.target.value })}>
            <option value="year_desc">Newest first</option>
            <option value="year_asc">Oldest first</option>
            <option value="cited">Most cited</option>
            <option value="title">Title A–Z</option>
          </select>
        </label>
      </section>

      <div className="ep-results-head">
        <p>
          {listing.data ? (
            <>
              <strong>{formatNumber(listing.data.total)}</strong> papers
              {journal !== 'all' ? ` in ${journal}` : ''}
              {qParam ? ` matching “${qParam}”` : ''}
            </>
          ) : (
            'Loading papers'
          )}
        </p>
        <button
          type="button"
          className="ep-text-button"
          onClick={() => {
            setQInput('')
            setParams({}, { replace: true })
          }}
        >
          Reset filters
        </button>
      </div>

      {listing.loading && <LoadingState label="Loading papers" />}
      {listing.error && <ErrorState message={listing.error} />}
      {listing.data && listing.data.items.length === 0 && (
        <EmptyState title="No papers match these filters.">
          <p>Try a broader search or widen the year range.</p>
        </EmptyState>
      )}
      {listing.data && listing.data.items.length > 0 && (
        <>
          <div className="ep-paper-list is-index">
            {listing.data.items.map((paper) => (
              <PaperRow key={paper.doi} paper={paper} />
            ))}
          </div>
          <Pagination
            page={listing.data.page}
            pages={listing.data.pages}
            onPage={(nextPage) => update({ page: nextPage })}
          />
        </>
      )}
    </div>
  )
}
