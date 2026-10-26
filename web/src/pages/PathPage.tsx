import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { ErrorState, LoadingState } from '../components/States'
import { formatNumber, useApi, useDebounced } from '../lib'

interface PickedAuthor {
  id: string
  name: string
}

function AuthorPicker({
  label,
  value,
  onChange,
  journal,
  placeholder,
}: {
  label: string
  value: PickedAuthor | null
  onChange: (author: PickedAuthor | null) => void
  journal: string
  placeholder: string
}) {
  const [query, setQuery] = useState('')
  const debounced = useDebounced(query, 220)
  const suggestions = useApi(
    () =>
      debounced.trim().length >= 2
        ? api.authors({
            q: debounced.trim(),
            journal: journal === 'all' ? undefined : journal,
            page_size: 6,
          })
        : Promise.resolve(null),
    [debounced, journal],
  )

  if (value) {
    return (
      <div className="ep-field ep-picked-author">
        <span>{label}</span>
        <div className="ep-picked-author-row">
          <Link to={`/authors/${value.id}`}>{value.name}</Link>
          <button type="button" className="ep-text-button" onClick={() => onChange(null)}>
            Change
          </button>
        </div>
      </div>
    )
  }

  return (
    <label className="ep-field ep-author-picker">
      <span>{label}</span>
      <input
        type="search"
        value={query}
        placeholder={placeholder}
        onChange={(event) => setQuery(event.target.value)}
      />
      {suggestions.data && suggestions.data.items.length > 0 && (
        <div className="ep-picker-results">
          {suggestions.data.items.map((author) => (
            <button
              type="button"
              key={author.stable_id}
              className="ep-picker-option"
              onClick={() => {
                onChange({ id: author.stable_id, name: author.name })
                setQuery('')
              }}
            >
              <strong>{author.name}</strong>
              <small>
                {author.institution ?? 'Institution not resolved'} · {author.papers} papers
              </small>
            </button>
          ))}
        </div>
      )}
    </label>
  )
}

export default function PathPage() {
  const [params, setParams] = useSearchParams()
  const fromId = params.get('from') ?? ''
  const toId = params.get('to') ?? ''
  const journal = params.get('journal') ?? 'all'
  const [fromAuthor, setFromAuthor] = useState<PickedAuthor | null>(null)
  const [toAuthor, setToAuthor] = useState<PickedAuthor | null>(null)
  const overview = useApi(() => api.overview(), [])
  const journalOptions = overview.data?.dataset.journals ?? []

  useEffect(() => {
    if (fromAuthor && fromAuthor.id !== fromId) {
      setFromAuthor(null)
    }
    if (toAuthor && toAuthor.id !== toId) {
      setToAuthor(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fromId, toId])

  function update(values: Record<string, string | null>) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(values)) {
      if (value === null || value === '') next.delete(key)
      else next.set(key, value)
    }
    setParams(next, { replace: true })
  }

  const result = useApi(
    () =>
      fromId && toId
        ? api.path({
            from: fromId,
            to: toId,
            journal: journal === 'all' ? undefined : journal,
          })
        : Promise.resolve(null),
    [fromId, toId, journal],
  )

  useEffect(() => {
    if (!fromId || !toId || !result.data) return
    if (!fromAuthor && result.data.from.id === fromId) {
      setFromAuthor({ id: result.data.from.id, name: result.data.from.name })
    }
    if (!toAuthor && result.data.to.id === toId) {
      setToAuthor({ id: result.data.to.id, name: result.data.to.name })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result.data, fromId, toId])

  const fromLabel = fromAuthor?.name ?? result.data?.from.name ?? fromId
  const toLabel = toAuthor?.name ?? result.data?.to.name ?? toId
  const path = result.data?.found ? result.data : null

  return (
    <div className="ep-page">
      <header className="ep-page-head">
        <p className="ep-kicker">Connection finder</p>
        <h1>How are two authors connected?</h1>
        <p className="ep-page-deck">
          Find the shortest coauthorship chain between two authors. Each step is one coauthored
          paper; the result shows the papers that connect each pair.
        </p>
      </header>

      <section className="ep-panel ep-path-panel">
        <div className="ep-path-pickers">
          <AuthorPicker
            label="From"
            value={fromAuthor}
            journal={journal}
            placeholder="Search an author"
            onChange={(author) => {
              setFromAuthor(author)
              update({ from: author?.id ?? null })
            }}
          />
          <span className="ep-path-arrow" aria-hidden="true">
            →
          </span>
          <AuthorPicker
            label="To"
            value={toAuthor}
            journal={journal}
            placeholder="Search an author"
            onChange={(author) => {
              setToAuthor(author)
              update({ to: author?.id ?? null })
            }}
          />
        </div>
        {journalOptions.length > 1 && (
          <label className="ep-field ep-path-journal">
            <span>Network scope</span>
            <select
              value={journal}
              onChange={(event) =>
                update({ journal: event.target.value === 'all' ? null : event.target.value })
              }
            >
              <option value="all">All five journals</option>
              {journalOptions.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.code} — {item.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {fromId && toId && (
          <p className="ep-note">
            Searching the {journal === 'all' ? 'combined five-journal' : journal} coauthorship
            graph. The graph is unweighted: one coauthored paper is one step.
          </p>
        )}
      </section>

      {result.loading && <LoadingState label="Tracing the shortest path" />}
      {result.error && <ErrorState message={result.error} />}
      {result.data && !result.data.found && (
        <section className="ep-panel">
          <h2>No connection found</h2>
          <p>
            {fromLabel} and {toLabel} are not connected within the search depth in this scope.
            {result.data.meta.source_component_size && result.data.meta.target_component_size ? (
              <>
                {' '}
                They sit in components of {formatNumber(result.data.meta.source_component_size)} and{' '}
                {formatNumber(result.data.meta.target_component_size)} authors.
              </>
            ) : null}
          </p>
          <p className="ep-muted">
            Try “All five journals” or a different pair. A missing path means the two authors
            have no chain of coauthored papers in this graph; it is not a claim that they never
            interacted.
          </p>
        </section>
      )}
      {path && path.found && (
        <section className="ep-panel ep-path-result">
          <div className="ep-path-summary">
            <div>
              <p className="ep-kicker">
                {path.distance === 0 ? 'Same author' : `${path.distance} steps`}
              </p>
              <h2>
                {fromLabel}
                {path.distance === 0 ? '' : ` → ${toLabel}`}
              </h2>
            </div>
            <span className="ep-path-graph-meta">
              {formatNumber(path.meta.graph_nodes)} authors ·{' '}
              {formatNumber(path.meta.graph_edges)} ties in scope
            </span>
          </div>

          {path.distance === 0 ? (
            <p>Both selections point to the same canonical author.</p>
          ) : (
            <>
              <div className="ep-path-chain" aria-label="Shortest coauthorship chain">
                {path.nodes.map((node, index) => (
                  <span className="ep-path-chain-node" key={node.id}>
                    {index > 0 && <span className="ep-path-chain-arrow">→</span>}
                    <Link to={`/authors/${node.id}`}>{node.name}</Link>
                  </span>
                ))}
              </div>

              <ol className="ep-path-steps">
                {path.steps.map((step, index) => {
                  const from =
                    path.nodes.find((node) => node.id === step.from)?.name ?? step.from
                  const to =
                    path.nodes.find((node) => node.id === step.to)?.name ?? step.to
                  return (
                    <li className="ep-path-step" key={`${step.from}-${step.to}-${index}`}>
                      <div className="ep-path-step-head">
                        <span className="ep-path-step-index">{String(index + 1).padStart(2, '0')}</span>
                        <strong>
                          {from} ↔ {to}
                        </strong>
                        {step.shared_papers ? (
                          <small className="ep-path-step-count">
                            {step.papers.length} of {step.shared_papers} shared papers
                          </small>
                        ) : null}
                      </div>
                      <ul className="ep-path-papers">
                        {step.papers.map((paper) => (
                          <li key={paper.doi}>
                            <span className="ep-flag is-journal">{paper.journal}</span>
                            <Link to={`/papers/${paper.doi}`}>{paper.title}</Link>
                            {paper.year ? <small>{paper.year}</small> : null}
                          </li>
                        ))}
                      </ul>
                    </li>
                  )
                })}
              </ol>
            </>
          )}
          <p className="ep-note">
            This is one shortest path, not necessarily the only one. Distance is the number of
            coauthored papers in the chain; multiple shared papers do not shorten it.
          </p>
        </section>
      )}
    </div>
  )
}
