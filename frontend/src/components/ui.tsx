import { AlertCircle, ChevronDown, CircleOff, LoaderCircle } from 'lucide-react'
import type { ComponentProps, ReactNode } from 'react'
import type { PollState } from '../usePoll'
import { formatType } from '../format'

export function Select({ children, className = '', ...props }: ComponentProps<'select'>) {
  return (
    <span className={`select-wrap ${className}`}>
      <select {...props}>{children}</select>
      <ChevronDown size={14} aria-hidden="true" />
    </span>
  )
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`status-badge status-${status}`}>
      <span className="status-dot" aria-hidden="true" />
      {formatType(status)}
    </span>
  )
}

export function EmptyState({ icon, title, children }: {
  icon?: ReactNode
  title: string
  children?: ReactNode
}) {
  return (
    <div className="empty-state">
      {icon && <span className="empty-icon">{icon}</span>}
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  )
}

export function Loading({ label }: { label: string }) {
  return <div className="loading" role="status"><LoaderCircle size={19} className="animate-spin" />{label}</div>
}

export function ErrorNotice({ state, onRetry }: {
  state: PollState<unknown>
  onRetry: () => void
}) {
  if (state.status !== 'disconnected' && state.status !== 'error') return null
  const Icon = state.status === 'disconnected' ? CircleOff : AlertCircle
  return (
    <div className="notice" role="alert">
      <Icon size={19} aria-hidden="true" />
      <div>
        <strong>{state.status === 'disconnected' ? 'Disconnected from the API' : 'Could not refresh data'}</strong>
        <p>{state.error}{state.data !== null && ' Showing the last successful response.'}</p>
      </div>
      <button className="button button-small" onClick={onRetry}>Retry</button>
    </div>
  )
}
