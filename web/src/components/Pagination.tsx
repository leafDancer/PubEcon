export default function Pagination({
  page,
  pages,
  onPage,
}: {
  page: number
  pages: number
  onPage: (page: number) => void
}) {
  if (pages <= 1) return null
  const windowStart = Math.max(1, Math.min(page - 2, pages - 4))
  const windowEnd = Math.min(pages, windowStart + 4)
  const numbers = []
  for (let value = windowStart; value <= windowEnd; value += 1) numbers.push(value)
  return (
    <nav className="ep-pagination" aria-label="Pagination">
      <button type="button" onClick={() => onPage(page - 1)} disabled={page <= 1}>
        Previous
      </button>
      {numbers.map((value) => (
        <button
          key={value}
          type="button"
          className={value === page ? 'is-current' : undefined}
          aria-current={value === page ? 'page' : undefined}
          onClick={() => onPage(value)}
        >
          {value}
        </button>
      ))}
      <button type="button" onClick={() => onPage(page + 1)} disabled={page >= pages}>
        Next
      </button>
    </nav>
  )
}
