import { Check, CircleAlert, Clock3, Layers3, LoaderCircle, RotateCw, Timer } from 'lucide-react'
import { lazy, Suspense } from 'react'
import { formatCount, formatDuration } from '../format'
import type { Job, JobPage, Overview, TimeWindow } from '../types'
import type { PollState } from '../usePoll'
import { RecentJobs } from './Jobs'
import { Loading } from './ui'

const Throughput = lazy(() => import('./Charts').then((module) => ({ default: module.Throughput })))
const Outcomes = lazy(() => import('./Charts').then((module) => ({ default: module.Outcomes })))
const CompletionChart = lazy(() => import('./Charts').then((module) => ({ default: module.CompletionChart })))
const Benchmarks = lazy(() => import('./Benchmarks'))

const metrics = [
  { key: 'total', label: 'Total jobs', icon: Layers3 },
  { key: 'pending', label: 'Pending', icon: Clock3 },
  { key: 'running', label: 'Running', icon: LoaderCircle },
  { key: 'completed', label: 'Completed', icon: Check },
  { key: 'failed', label: 'Failed', icon: CircleAlert },
] as const

export function OverviewPage({ data, recent, window, onInspect }: {
  data: PollState<Overview>
  recent: PollState<JobPage> & { refresh: () => void }
  window: TimeWindow
  onInspect: (job: Job) => void
}) {
  return (
    <div className="page-stack">
      <div className="metric-grid">
        {metrics.map(({ key, label, icon: Icon }) => (
          <section key={key} className="panel metric">
            <span className={`metric-icon tone-${key}`}><Icon size={19} strokeWidth={2} aria-hidden="true" /></span>
            <h2>{label}</h2>
            <strong>{data.data ? formatCount(data.data.counts[key]) : '—'}</strong>
          </section>
        ))}
      </div>
      {data.data ? <Suspense fallback={<div className="panel"><Loading label="Loading charts" /></div>}>
        <div className="overview-charts"><Throughput data={data.data} window={window} /><Outcomes period={data.data.period} /></div>
      </Suspense>
        : data.status === 'loading' && <div className="panel"><Loading label="Loading monitoring data" /></div>}
      <RecentJobs state={recent} onInspect={onInspect} />
    </div>
  )
}

export function AnalyticsPage({ state, window }: { state: PollState<Overview>; window: TimeWindow }) {
  const benchmark = <Suspense fallback={<div className="panel"><Loading label="Loading benchmark charts" /></div>}>
    <Benchmarks />
  </Suspense>
  if (!state.data) return <div className="page-stack">
    {state.status === 'loading' && <div className="panel"><Loading label="Loading performance data" /></div>}
    {benchmark}
  </div>
  const data = state.data
  const { duration } = data.period
  const durationMetrics = [
    { label: 'Average', value: duration.average_ms },
    { label: 'Fastest', value: duration.minimum_ms },
    { label: '95th percentile', value: duration.p95_ms },
    { label: 'Slowest', value: duration.maximum_ms },
  ]
  const retries = [
    { label: 'Jobs retried', value: data.period.retried_jobs },
    { label: 'Retry attempts', value: data.period.retry_attempts },
    { label: 'Failed attempts', value: data.period.failed_attempts },
    { label: 'Abandoned attempts', value: data.period.abandoned_attempts },
  ]
  return (
    <div className="page-stack">
      <div className="analytics-grid">
        <section className="panel summary-panel">
          <div className="panel-heading">
            <div><h2>Execution duration</h2><p>{formatCount(duration.samples)} measured {duration.samples === 1 ? 'attempt' : 'attempts'} in this range</p></div>
            <span className="panel-symbol"><Timer size={18} aria-hidden="true" /></span>
          </div>
          <dl className="summary-grid">{durationMetrics.map(({ label, value }) => (
            <div key={label}><dt>{label}</dt><dd>{formatDuration(value)}</dd></div>
          ))}</dl>
        </section>
        <section className="panel summary-panel">
          <div className="panel-heading">
            <div><h2>Failures and retries</h2><p>Recorded attempts started in this range</p></div>
            <span className="panel-symbol"><RotateCw size={18} aria-hidden="true" /></span>
          </div>
          <dl className="summary-grid">{retries.map(({ label, value }) => (
            <div key={label}><dt>{label}</dt><dd>{formatCount(value)}</dd></div>
          ))}</dl>
        </section>
      </div>
      {benchmark}
      <Suspense fallback={<div className="panel"><Loading label="Loading charts" /></div>}>
        <Throughput data={data} window={window} />
        <CompletionChart data={data} window={window} />
      </Suspense>
    </div>
  )
}
