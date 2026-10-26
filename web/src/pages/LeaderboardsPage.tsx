import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { ErrorState, LoadingState } from '../components/States'
import { formatNumber, formatPct, useApi } from '../lib'

const BOARDS = [
  { id: 'assistant_professor', label: 'Assistant professors' },
  { id: 'five_journal', label: 'Five-journal club' },
  { id: 'most_coauthors', label: 'Most coauthors' },
  { id: 'strongest_pair', label: 'Strongest pairs' },
  { id: 'largest_teams', label: 'Largest teams' },
  { id: 'longest_careers', label: 'Longest careers' },
  { id: 'institutions', label: 'Institutions' },
] as const

type Board = (typeof BOARDS)[number]['id']
const LIMITS = [10, 25, 50, 100]

export default function LeaderboardsPage() {
  const [params, setParams] = useSearchParams()
  const requestedBoard = params.get('board') as Board | null
  const board: Board = BOARDS.some((item) => item.id === requestedBoard)
    ? (requestedBoard as Board)
    : 'assistant_professor'
  const requestedLimit = Number(params.get('limit') ?? 50)
  const limit = LIMITS.includes(requestedLimit) ? requestedLimit : 50
  const rankings = useApi(() => api.rankings(limit), [limit])
  const data = rankings.data

  function update(values: Record<string, string | number>) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(values)) next.set(key, String(value))
    setParams(next, { replace: true })
  }

  const definition = data?.definitions[board]

  return (
    <div className="ep-page">
      <header className="ep-page-head">
        <p className="ep-kicker">Rankings</p>
        <h1>Leaderboards</h1>
        <p className="ep-page-deck">
          Descriptive rankings across the five journals. Coverage and confidence travel with every
          metric; a high position is not a claim about quality.
        </p>
      </header>

      <section className="ep-filters" aria-label="Leaderboard controls">
        <label className="ep-field ep-field-wide">
          <span>Leaderboard</span>
          <select value={board} onChange={(event) => update({ board: event.target.value })}>
            {BOARDS.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="ep-field">
          <span>Rows</span>
          <select
            value={limit}
            onChange={(event) => update({ limit: Number(event.target.value) })}
          >
            {LIMITS.map((value) => (
              <option key={value} value={value}>
                Top {value}
              </option>
            ))}
          </select>
        </label>
      </section>

      {rankings.loading && <LoadingState label="Loading leaderboard" />}
      {rankings.error && <ErrorState message={rankings.error} />}
      {data && (
        <section className="ep-panel ep-leaderboard-panel">
          <div className="ep-section-heading">
            <div>
              <h2>{BOARDS.find((item) => item.id === board)?.label}</h2>
              <p>{definition}</p>
            </div>
            <Link className="ep-text-link" to="/methodology#rankings">
              Ranking rules
            </Link>
          </div>

          <div className="ep-table-wrap">
            <table className="ep-table ep-leaderboard-table">
              {board === 'assistant_professor' && (
                <>
                  <thead>
                    <tr>
                      <th scope="col">#</th>
                      <th scope="col">Author</th>
                      <th scope="col">Institution</th>
                      <th scope="col">Assistant papers</th>
                      <th scope="col">Known stage</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.assistant_professor.map((row, index) => (
                      <tr key={row.id}>
                        <td className="ep-num">{index + 1}</td>
                        <td>
                          <Link to={`/authors/${row.id}`}>{row.name}</Link>
                        </td>
                        <td>{row.institution ?? '—'}</td>
                        <td className="ep-num">{row.assistant_papers}</td>
                        <td className="ep-num">{formatPct(row.coverage ?? 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </>
              )}

              {board === 'five_journal' && (
                <>
                  <thead>
                    <tr>
                      <th scope="col">#</th>
                      <th scope="col">Author</th>
                      <th scope="col">Institution</th>
                      <th scope="col">Papers</th>
                      <th scope="col">Journals</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.five_journal.map((row, index) => (
                      <tr key={row.id}>
                        <td className="ep-num">{index + 1}</td>
                        <td>
                          <Link to={`/authors/${row.id}`}>{row.name}</Link>
                        </td>
                        <td>{row.institution ?? '—'}</td>
                        <td className="ep-num">{row.papers}</td>
                        <td className="ep-num">{row.journals}</td>
                      </tr>
                    ))}
                  </tbody>
                </>
              )}

              {board === 'most_coauthors' && (
                <>
                  <thead>
                    <tr>
                      <th scope="col">#</th>
                      <th scope="col">Author</th>
                      <th scope="col">Institution</th>
                      <th scope="col">Coauthors</th>
                      <th scope="col">Papers</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.most_coauthors.map((row, index) => (
                      <tr key={row.id}>
                        <td className="ep-num">{index + 1}</td>
                        <td>
                          <Link to={`/authors/${row.id}`}>{row.name}</Link>
                        </td>
                        <td>{row.institution ?? '—'}</td>
                        <td className="ep-num">{row.coauthors}</td>
                        <td className="ep-num">{row.papers}</td>
                      </tr>
                    ))}
                  </tbody>
                </>
              )}

              {board === 'strongest_pair' && (
                <>
                  <thead>
                    <tr>
                      <th scope="col">#</th>
                      <th scope="col">Pair</th>
                      <th scope="col">Shared papers</th>
                      <th scope="col">Years</th>
                      <th scope="col">Evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.strongest_pair.map((pair, index) => (
                      <tr key={`${pair.a.id}-${pair.b.id}`}>
                        <td className="ep-num">{index + 1}</td>
                        <td>
                          <Link to={`/authors/${pair.a.id}`}>{pair.a.name}</Link>
                          {' & '}
                          <Link to={`/authors/${pair.b.id}`}>{pair.b.name}</Link>
                        </td>
                        <td className="ep-num">{pair.shared_papers}</td>
                        <td className="ep-num">
                          {pair.first_year ?? '—'}–{pair.last_year ?? '—'}
                        </td>
                        <td>
                          {pair.papers.slice(0, 3).map((paper) => (
                            <div key={paper.doi}>
                              <Link to={`/papers/${paper.doi}`}>{paper.title}</Link>
                            </div>
                          ))}
                          {pair.shared_papers > pair.papers.length ? (
                            <small>
                              +{pair.shared_papers - pair.papers.length} more not shown
                            </small>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </>
              )}

              {board === 'largest_teams' && (
                <>
                  <thead>
                    <tr>
                      <th scope="col">#</th>
                      <th scope="col">Paper</th>
                      <th scope="col">Journal</th>
                      <th scope="col">Year</th>
                      <th scope="col">Authors</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.largest_teams.map((paper, index) => (
                      <tr key={paper.doi}>
                        <td className="ep-num">{index + 1}</td>
                        <td>
                          <Link to={`/papers/${paper.doi}`}>{paper.title}</Link>
                        </td>
                        <td>{paper.journal}</td>
                        <td className="ep-num">{paper.year ?? '—'}</td>
                        <td className="ep-num">{paper.authors}</td>
                      </tr>
                    ))}
                  </tbody>
                </>
              )}

              {board === 'longest_careers' && (
                <>
                  <thead>
                    <tr>
                      <th scope="col">#</th>
                      <th scope="col">Author</th>
                      <th scope="col">Institution</th>
                      <th scope="col">Span</th>
                      <th scope="col">Years</th>
                      <th scope="col">Papers</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.longest_careers.map((row, index) => (
                      <tr key={row.id}>
                        <td className="ep-num">{index + 1}</td>
                        <td>
                          <Link to={`/authors/${row.id}`}>{row.name}</Link>
                        </td>
                        <td>{row.institution ?? '—'}</td>
                        <td className="ep-num">{row.span} yrs</td>
                        <td className="ep-num">
                          {row.first_year ?? '—'}–{row.last_year ?? '—'}
                        </td>
                        <td className="ep-num">{row.papers}</td>
                      </tr>
                    ))}
                  </tbody>
                </>
              )}

              {board === 'institutions' && (
                <>
                  <thead>
                    <tr>
                      <th scope="col">#</th>
                      <th scope="col">Institution</th>
                      <th scope="col">Country</th>
                      <th scope="col">Author slots</th>
                      <th scope="col">Authors</th>
                      <th scope="col">Papers</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.institutions.map((row, index) => (
                      <tr key={row.name}>
                        <td className="ep-num">{index + 1}</td>
                        <td>{row.name}</td>
                        <td>{row.country ?? '—'}</td>
                        <td className="ep-num">{formatNumber(row.slots)}</td>
                        <td className="ep-num">{formatNumber(row.authors)}</td>
                        <td className="ep-num">{formatNumber(row.papers)}</td>
                      </tr>
                    ))}
                  </tbody>
                </>
              )}
            </table>
          </div>
        </section>
      )}
    </div>
  )
}
