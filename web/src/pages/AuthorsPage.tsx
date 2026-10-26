import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import AuthorRow from '../components/AuthorRow'
import Pagination from '../components/Pagination'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { formatNumber, STAGE_LABELS, STAGE_ORDER, useApi, useDebounced } from '../lib'

const YEARS = Array.from({ length: 27 }, (_, index) => 2000 + index)

export default function AuthorsPage() {
  const [params, setParams] = useSearchParams()
  const qParam = params.get('q') ?? ''
  const stage = params.get('stage') ?? 'all'
  const journal = params.get('journal') ?? 'all'
  const yearFrom = Number(params.get('year_from') ?? 2000)
  const yearTo = Number(params.get('year_to') ?? 2026)
  const sort = params.get('sort') ?? 'papers'
  const page = Math.max(1, Number(params.get('page') ?? 1))
  const [qInput, setQInput] = useState(qParam)
  const debouncedQ = useDebounced(qInput, 260)

  function update(values: Record<string, string | number | null>) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(values)) {
      if (value === null || value === '') next.delete(key)
      else next.set(key, String(value))
    }
    if (!('page' in values)) next.delete('page')
    setParams(next, { replace: true })
  }

  useEffect(() => {
    if (debouncedQ !== qParam) update({ q: debouncedQ || null })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ])

  useEffect(() => {
    if (qParam !== qInput) setQInput(qParam)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qParam])

  const overview = useApi(() => api.overview(), [])
  const journalOptions = overview.data?.dataset.journals ?? []

  const listing = useApi(
    () =>
      api.authors({
        q: qParam,
        stage: stage === 'all' ? undefined : stage,
        journal: journal === 'all' ? undefined : journal,
        year_from: yearFrom,
        year_to: yearTo,
        sort,
        page,
        page_size: 25,
      }),
    [qParam, stage, journal, yearFrom, yearTo, sort, page],
  )

  return (
    <div className="ep-page">
      <header className="ep-page-head">
        <p className="ep-kicker">People</p>
        <h1>Authors</h1>
        <p className="ep-page-deck">
          Canonical author identities, the papers they published across the top five journals, and
          the career stage evidence attached to each appearance.
        </p>
      </header>

      <section className="ep-filters" aria-label="Filter authors">
        <label className="ep-field ep-field-search">
          <span>Search authors</span>
          <input
            type="search"
            value={qInput}
            placeholder="e.g. Acemoglu, Chetty, Duflo"
            onChange={(event) => setQInput(event.target.value)}
          />
        </label>
        {journalOptions.length > 1 && (
          <label className="ep-field">
            <span>Journal</span>
            <select
              value={journal}
              onChange={(event) =>
                update({ journal: event.target.value === 'all' ? null : event.target.value })
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
          <span>Stage</span>
          <select value={stage} onChange={(event) => update({ stage: event.target.value })}>
            <option value="all">Any known stage</option>
            {STAGE_ORDER.filter((value) => value in STAGE_LABELS).map((value) => (
              <option key={value} value={value}>
                {STAGE_LABELS[value]}
              </option>
            ))}
          </select>
        </label>
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
        <label className="ep-field">
          <span>Sort</span>
          <select value={sort} onChange={(event) => update({ sort: event.target.value })}>
            <option value="papers">Most papers</option>
            <option value="name">Name A–Z</option>
            <option value="first_year">First year</option>
            <option value="recent">Most recent</option>
          </select>
        </label>
      </section>

      <div className="ep-results-head">
        <p>
          {listing.data ? (
            <>
              <strong>{formatNumber(listing.data.total)}</strong> authors
              {journal !== 'all' ? ` in ${journal}` : ''}
              {qParam ? ` matching “${qParam}”` : ''}
            </>
          ) : (
            'Loading authors'
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

      {listing.loading && <LoadingState label="Loading authors" />}
      {listing.error && <ErrorState message={listing.error} />}
      {listing.data && listing.data.items.length === 0 && (
        <EmptyState title="No authors match these filters.">
          <p>Try a broader name search or remove the stage filter.</p>
        </EmptyState>
      )}
      {listing.data && listing.data.items.length > 0 && (
        <>
          <div className="ep-author-list">
            {listing.data.items.map((author) => (
              <AuthorRow key={author.stable_id} author={author} />
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
