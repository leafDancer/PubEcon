import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import NetworkGraph from '../components/NetworkGraph'
import { ErrorState, LoadingState } from '../components/States'
import { formatNumber, stageLabel, useApi, useDebounced } from '../lib'

const PRESETS = [
  { label: 'All years', from: 2000, to: 2026 },
  { label: '2000–2010', from: 2000, to: 2010 },
  { label: '2011–2020', from: 2011, to: 2020 },
  { label: '2021–2026', from: 2021, to: 2026 },
]

export default function NetworkPage() {
  const [params, setParams] = useSearchParams()
  const focus = params.get('focus') ?? ''
  const yearFrom = Number(params.get('year_from') ?? 2000)
  const yearTo = Number(params.get('year_to') ?? 2026)
  const limit = Number(params.get('limit') ?? 120)
  const minPapers = Number(params.get('min_papers') ?? 2)
  const [searchQ, setSearchQ] = useState('')
  const debouncedSearch = useDebounced(searchQ, 220)

  const suggestions = useApi(
    () =>
      debouncedSearch.trim()
        ? api.authors({ q: debouncedSearch.trim(), page_size: 6 })
        : Promise.resolve(null),
    [debouncedSearch],
  )

  const graph = useApi(
    () =>
      focus
        ? api.authorNetwork(focus, 60)
        : api.network({
            year_from: yearFrom,
            year_to: yearTo,
            limit,
            min_papers: minPapers,
          }),
    [focus, yearFrom, yearTo, limit, minPapers],
  )

  function update(values: Record<string, string | number | null>) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(values)) {
      if (value === null || value === '') next.delete(key)
      else next.set(key, String(value))
    }
    setParams(next, { replace: true })
  }

  const focusName = graph.data?.nodes.find((node) => node.id === focus)?.name

  return (
    <div className="ep-page ep-network-page">
      <header className="ep-page-head">
        <p className="ep-kicker">Relationships</p>
        <h1>Coauthor network</h1>
        <p className="ep-page-deck">
          A filtered view of the coauthorship record. The page never sends the full graph: choose a
          year range for a ranked sample, or open one author&apos;s ego network.
        </p>
      </header>

      <section className="ep-network-controls" aria-label="Network controls">
        {!focus && (
          <>
            <label className="ep-field">
              <span>Year range</span>
              <select
                value={`${yearFrom}-${yearTo}`}
                onChange={(event) => {
                  const preset = PRESETS.find(
                    (item) => `${item.from}-${item.to}` === event.target.value,
                  )
                  if (preset) update({ year_from: preset.from, year_to: preset.to })
                }}
              >
                {PRESETS.map((preset) => (
                  <option key={preset.label} value={`${preset.from}-${preset.to}`}>
                    {preset.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="ep-field">
              <span>Minimum papers</span>
              <select
                value={minPapers}
                onChange={(event) => update({ min_papers: Number(event.target.value) })}
              >
                {[1, 2, 3, 5, 8].map((value) => (
                  <option key={value} value={value}>
                    {value}+
                  </option>
                ))}
              </select>
            </label>
            <label className="ep-field">
              <span>Authors in view</span>
              <select value={limit} onChange={(event) => update({ limit: Number(event.target.value) })}>
                {[60, 120, 240, 400].map((value) => (
                  <option key={value} value={value}>
                    Top {value}
                  </option>
                ))}
              </select>
            </label>
          </>
        )}
        <div className="ep-field ep-field-search ep-network-focus">
          <span>Focus on an author</span>
          <input
            type="search"
            value={searchQ}
            placeholder="Search a name"
            onChange={(event) => setSearchQ(event.target.value)}
          />
          {debouncedSearch.trim() && suggestions.data && suggestions.data.items.length > 0 && (
            <ul className="ep-suggestions">
              {suggestions.data.items.map((author) => (
                <li key={author.stable_id}>
                  <button
                    type="button"
                    onClick={() => {
                      update({ focus: author.stable_id })
                      setSearchQ('')
                    }}
                  >
                    <span>{author.name}</span>
                    <small>{author.papers} papers</small>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      {focus && (
        <div className="ep-focus-banner">
          <p>
            Ego network for <Link to={`/authors/${focus}`}>{focusName ?? focus}</Link>
            {graph.data?.meta.total_coauthors
              ? `, ${formatNumber(graph.data.meta.total_coauthors)} coauthors in the record`
              : ''}
          </p>
          <button type="button" className="ep-text-button" onClick={() => update({ focus: null })}>
            Clear focus
          </button>
        </div>
      )}

      {!focus && (
        <p className="ep-network-note">
          Showing the top {formatNumber(graph.data?.meta.selected ?? limit)} authors in the selected
          range, not the complete graph. A tie is one coauthored paper, and ties
          may connect papers in different journals.
        </p>
      )}

      {graph.loading && <LoadingState label="Building the network view" />}
      {graph.error && <ErrorState message={graph.error} />}
      {graph.data && graph.data.nodes.length === 0 && (
        <p className="ep-empty-inline">No authors match this network view.</p>
      )}
      {graph.data && graph.data.nodes.length > 0 && (
        <>
          <NetworkGraph nodes={graph.data.nodes} edges={graph.data.edges} />
          <section className="ep-panel ep-network-table-panel">
            <div className="ep-section-heading">
              <div>
                <h2>Authors in this view</h2>
                <p>Ranked by papers in the selected range. Node colour carries confidence.</p>
              </div>
            </div>
            <div className="ep-table-wrap">
              <table className="ep-table">
                <thead>
                  <tr>
                    <th scope="col">Author</th>
                    <th scope="col">Institution</th>
                    <th scope="col">Papers</th>
                    <th scope="col">Stage</th>
                    <th scope="col">Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {[...graph.data.nodes]
                    .sort((a, b) => b.papers - a.papers)
                    .slice(0, 30)
                    .map((node) => (
                      <tr key={node.id}>
                        <td>
                          <Link to={`/authors/${node.id}`}>{node.name}</Link>
                        </td>
                        <td>{node.institution ?? '—'}</td>
                        <td>{node.papers}</td>
                        <td>{stageLabel(node.stage)}</td>
                        <td>{node.confidence}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
