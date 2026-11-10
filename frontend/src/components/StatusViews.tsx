import type { ReactNode } from 'react'
import { Link } from 'react-router'

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <p className="status" role="status">
      <span className="spinner" aria-hidden="true" /> {label}
    </p>
  )
}

interface LoadErrorProps {
  message: string
  onRetry?: () => void
  children?: ReactNode
}

export function LoadError({ message, onRetry, children }: LoadErrorProps) {
  return (
    <div className="alert alert-error" role="alert">
      <p>{message}</p>
      <div className="actions">
        {onRetry && (
          <button type="button" className="btn" onClick={onRetry}>
            Try again
          </button>
        )}
        {children}
      </div>
    </div>
  )
}

export function NotFound({ what }: { what: string }) {
  return (
    <div className="empty-state">
      <h1>{what} not found</h1>
      <p>It may have been deleted.</p>
      <Link to="/" className="btn">
        Back to projects
      </Link>
    </div>
  )
}
