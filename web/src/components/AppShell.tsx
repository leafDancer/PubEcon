import { useEffect } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { api } from '../api'
import { formatNumber, useApi } from '../lib'

const nav = [
  { to: '/', label: 'Overview', end: true },
  { to: '/papers', label: 'Papers' },
  { to: '/authors', label: 'Authors' },
  { to: '/network', label: 'Network' },
  { to: '/connection', label: 'Connection' },
  { to: '/leaderboards', label: 'Leaderboards' },
  { to: '/methodology', label: 'Methodology' },
]

export default function AppShell() {
  const { data } = useApi(() => api.overview(), [])
  const location = useLocation()
  const journals = data?.dataset.journals ?? []
  const isMulti = journals.length !== 1
  const scopeLabel = isMulti ? 'Top 5' : journals[0]?.code ?? 'AER'

  useEffect(() => {
    if (!location.hash) return
    const target = document.getElementById(location.hash.slice(1))
    if (target) requestAnimationFrame(() => target.scrollIntoView())
  }, [location.pathname, location.hash])

  return (
    <div className="ep-shell">
      <a className="ep-skip" href="#main">
        Skip to content
      </a>
      <aside className="ep-rail">
        <div className="ep-rail-top">
          <NavLink to="/" className="ep-wordmark" end>
            <span className="ep-wordmark-name">EconPub</span>
            <span className="ep-wordmark-meta">{scopeLabel} 2000–2026</span>
          </NavLink>
          <nav className="ep-nav" aria-label="Primary">
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => (isActive ? 'ep-nav-link is-active' : 'ep-nav-link')}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="ep-rail-bottom">
          <p className="ep-rail-note">
            A public record of{' '}
            {isMulti ? (
              <em>the top five economics journals</em>
            ) : (
              <em>the American Economic Review</em>
            )}
            , built from publisher metadata, OpenAlex, ORCID, and public CVs.
          </p>
          <dl className="ep-rail-stats">
            <div>
              <dt>Papers</dt>
              <dd>{data ? formatNumber(data.counts.papers) : '—'}</dd>
            </div>
            <div>
              <dt>Authors</dt>
              <dd>{data ? formatNumber(data.counts.authors) : '—'}</dd>
            </div>
            <div>
              <dt>Career stages</dt>
              <dd>{data ? formatNumber(data.counts.career_assignments) : '—'}</dd>
            </div>
          </dl>
        </div>
      </aside>
      <div className="ep-main">
        <header className="ep-mobile-head">
          <NavLink to="/" className="ep-mobile-wordmark" end>
            EconPub
          </NavLink>
          <nav className="ep-mobile-nav" aria-label="Primary">
            {nav.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end}>
                {item.label}
              </NavLink>
            ))}
          </nav>
        </header>
        <main id="main" className="ep-content">
          <Outlet />
        </main>
        <footer className="ep-footer">
          <p>
            EconPub is an independent research project. Data is shown with provenance and
            confidence; missing evidence is never filled silently.
          </p>
          <p className="ep-footer-links">
            <NavLink to="/methodology">Methodology</NavLink>
            {isMulti ? (
              <NavLink to="/methodology#scope">Journal sources</NavLink>
            ) : (
              <a href="https://www.aeaweb.org/journals/aer" target="_blank" rel="noreferrer">
                AER at AEA
              </a>
            )}
            {isMulti ? (
              <a href="https://www.crossref.org" target="_blank" rel="noreferrer">
                Crossref
              </a>
            ) : (
              <a href="https://doi.org/10.1257/aer" target="_blank" rel="noreferrer">
                DOI prefix
              </a>
            )}
          </p>
        </footer>
      </div>
    </div>
  )
}
