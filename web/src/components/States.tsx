import type { ReactNode } from 'react'

export function LoadingState({ label = 'Loading the record' }: { label?: string }) {
  return (
    <div className="ep-state" role="status" aria-live="polite">
      <span className="ep-loading-mark" aria-hidden="true" />
      <p>{label}</p>
    </div>
  )
}

export function ErrorState({ message, children }: { message: string; children?: ReactNode }) {
  const notFound = message.toLowerCase().includes('not found')
  return (
    <div className="ep-state is-error" role="alert">
      <p className="ep-state-title">
        {notFound ? 'This record is not in the database.' : 'The record could not be loaded.'}
      </p>
      <p>{message}</p>
      {notFound ? (
        <p className="ep-state-hint">Check the identifier or return to the index.</p>
      ) : (
        <p className="ep-state-hint">
          Try again, or return to the index and choose another record.
        </p>
      )}
      {children}
    </div>
  )
}

export function EmptyState({
  title,
  children,
}: {
  title: string
  children?: ReactNode
}) {
  return (
    <div className="ep-state is-empty">
      <p className="ep-state-title">{title}</p>
      {children}
    </div>
  )
}
