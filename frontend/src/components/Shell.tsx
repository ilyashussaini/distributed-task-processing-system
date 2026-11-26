import { Activity, BarChart3, Boxes, ChevronRight, Layers3, LayoutDashboard, RefreshCw } from 'lucide-react'
import type { ReactNode } from 'react'
import { formatTime } from '../format'
import type { View } from '../types'
import type { PollState } from '../usePoll'

const views = {
  overview: { label: 'Overview', icon: LayoutDashboard },
  jobs: { label: 'Jobs', icon: Layers3 },
  analytics: { label: 'Analytics', icon: BarChart3 },
}

export function Shell({ view, state, refresh, demo, children }: {
  view: View
  state: PollState<unknown>
  refresh: () => void
  demo: boolean
  children: ReactNode
}) {
  const statusText = {
    ready: 'API connected', loading: 'Connecting', disconnected: 'Disconnected', error: 'API error',
  }[state.status]
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to dashboard</a>
      <aside className="sidebar">
        <a className="brand" href="#overview">
          <span className="brand-icon"><Boxes size={24} strokeWidth={1.8} /></span>
          <span><strong>Taskflow</strong><span>Distributed jobs</span></span>
        </a>
        <nav className="nav" aria-label="Dashboard">
          {(Object.keys(views) as View[]).map((key) => {
            const { label, icon: Icon } = views[key]
            return (
              <a className={view === key ? 'nav-link active' : 'nav-link'} aria-current={view === key ? 'page' : undefined} key={key} href={`#${key}`}>
                <Icon size={18} aria-hidden="true" /><span>{label}</span>
              </a>
            )
          })}
        </nav>
        <div className="sidebar-footer">
          <div className="workspace-icon"><Activity size={17} aria-hidden="true" /></div>
          <span><strong>Job monitoring</strong><span>{demo ? 'Sample dataset' : 'Auto-refresh every 5s'}</span></span>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumbs"><span>Workspace</span><ChevronRight size={14} aria-hidden="true" /><strong>{views[view].label}</strong></div>
          <div className="connection">
            {!demo && state.updatedAt !== null && <span className="last-sync">Updated {formatTime(state.updatedAt)}</span>}
            <span className={`connection-badge connection-${state.status}`} role="status">
              <span className="status-dot" aria-hidden="true" />{demo ? 'Sample data' : statusText}
            </span>
            {!demo && <button className="icon-button" onClick={refresh} aria-label="Refresh dashboard" title="Refresh dashboard">
              <RefreshCw size={16} aria-hidden="true" />
            </button>}
          </div>
        </header>
        <main id="main-content" tabIndex={-1} className="main-content">{children}</main>
      </div>
    </div>
  )
}
