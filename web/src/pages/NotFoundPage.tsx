import { Link } from 'react-router-dom'

export default function NotFoundPage() {
  return (
    <div className="ep-page ep-not-found">
      <p className="ep-kicker">404</p>
      <h1>This page is not in the record.</h1>
      <p>The link may be outdated, or the author or paper may not be part of the AER 2000+ corpus.</p>
      <div className="ep-actions">
        <Link className="ep-button" to="/">
          Return to the overview
        </Link>
        <Link className="ep-text-link" to="/papers">
          Browse papers
        </Link>
      </div>
    </div>
  )
}
