import { CalendarDays, Plus, ShieldCheck } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { getJobs, getOverview } from './api'
import { JobDetails, SubmitDialog } from './components/Dialogs'
import { JobHistory, PAGE_SIZE } from './components/Jobs'
import { AnalyticsPage, OverviewPage } from './components/Pages'
import { Shell } from './components/Shell'
import { ErrorNotice, Select } from './components/ui'
import { isDemoMode } from './demo'
import type { Job, JobStatus, TimeWindow, View } from './types'
import { usePoll } from './usePoll'

const viewLabels = {
  overview: ['Job overview', 'Retained job counts and activity for the selected range.'],
  jobs: ['Job history', 'Search and inspect submitted jobs, results, and retry attempts.'],
  analytics: ['Performance analytics', 'Review throughput, execution duration, and retry activity.'],
}

const ranges: Record<TimeWindow, string> = {
  '1h': 'Last hour', '24h': 'Last 24 hours', '7d': 'Last 7 days', '30d': 'Last 30 days',
}

function route(): View | undefined {
  const hash = location.hash.slice(1)
  if (hash === '' || hash === 'overview') return 'overview'
  if (hash === 'jobs' || hash === 'analytics') return hash
}

export function App() {
  const demo = isDemoMode()
  const [view, setView] = useState<View>(() => route() ?? 'overview')
  const [window, setWindow] = useState<TimeWindow>('24h')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<JobStatus | ''>('')
  const [page, setPage] = useState(0)
  const [submitOpen, setSubmitOpen] = useState(false)
  const [selected, setSelected] = useState<Job>()
  const [announcement, setAnnouncement] = useState('')

  useEffect(() => {
    function navigate() {
      const next = route()
      if (next) setView(next)
    }
    globalThis.addEventListener('hashchange', navigate)
    return () => globalThis.removeEventListener('hashchange', navigate)
  }, [])

  const loadOverview = useCallback((signal: AbortSignal) => getOverview(window, signal), [window])
  const loadRecent = useCallback((signal: AbortSignal) => getJobs(5, 0, '', '', signal), [])
  const loadHistory = useCallback(
    (signal: AbortSignal) => getJobs(PAGE_SIZE, PAGE_SIZE * page, query.trim(), status, signal),
    [page, query, status],
  )
  const interval = demo ? null : undefined
  const metrics = usePoll(window, loadOverview, view !== 'jobs', interval)
  const recent = usePoll('recent', loadRecent, view === 'overview', interval)
  const history = usePoll(JSON.stringify([page, query, status]), loadHistory, view === 'jobs', interval)
  const health = view === 'jobs' ? history : metrics

  function refresh() {
    if (view === 'jobs') history.refresh()
    else metrics.refresh()
    if (view === 'overview') recent.refresh()
  }

  function submitted(job: Job) {
    setSubmitOpen(false)
    setAnnouncement(`Job ${job.id.slice(0, 8)} submitted.`)
    setSelected(job)
    refresh()
  }

  const [title, subtitle] = viewLabels[view]
  return (
    <Shell view={view} state={health} refresh={refresh} demo={demo}>
      {demo && <div className="demo-note"><ShieldCheck size={17} aria-hidden="true" /><span><strong>Read-only demo</strong> · Explore sample jobs and recorded benchmarks.</span></div>}
      <div className="page-heading">
        <div><h1>{title}</h1><p>{subtitle}</p></div>
        <div className="page-actions">
          {view !== 'jobs' && <div className="range-control">
            <CalendarDays size={16} aria-hidden="true" />
            <Select aria-label="Time range" value={window} onChange={(event) => setWindow(event.target.value as TimeWindow)}>
              {(Object.keys(ranges) as TimeWindow[]).map((range) => <option value={range} key={range}>{ranges[range]}</option>)}
            </Select>
          </div>}
          {!demo && <button className="button button-primary" onClick={() => { setAnnouncement(''); setSubmitOpen(true) }}>
            <Plus size={18} aria-hidden="true" />New job
          </button>}
        </div>
      </div>
      <span className="sr-only" role="status" aria-live="polite">{announcement}</span>
      {view !== 'jobs' && <div className="page-notice"><ErrorNotice state={metrics} onRetry={metrics.refresh} /></div>}
      {view === 'overview' && <OverviewPage data={metrics} recent={recent} window={window} onInspect={setSelected} />}
      {view === 'jobs' && <JobHistory state={history} refresh={history.refresh} query={query} status={status} page={page}
        onQuery={(value) => { setQuery(value); setPage(0) }} onStatus={(value) => { setStatus(value); setPage(0) }}
        onPage={setPage} onInspect={setSelected} />}
      {view === 'analytics' && <AnalyticsPage state={metrics} window={window} />}
      {!demo && submitOpen && <SubmitDialog onClose={() => setSubmitOpen(false)} onSubmitted={submitted} />}
      {selected && <JobDetails key={selected.id} initial={selected} onClose={() => setSelected(undefined)} />}
    </Shell>
  )
}
