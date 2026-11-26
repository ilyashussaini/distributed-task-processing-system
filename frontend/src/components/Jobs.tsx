import { ChevronLeft, ChevronRight, FileText, Inbox, Search } from 'lucide-react'
import { formatCount, formatShortDate, formatTimestamp, formatType } from '../format'
import type { Job, JobPage, JobStatus } from '../types'
import type { PollState } from '../usePoll'
import { EmptyState, ErrorNotice, Loading, Select, StatusBadge } from './ui'

export const PAGE_SIZE = 10
export const jobStatuses = ['pending', 'running', 'completed', 'failed'] as const

export function JobTable({ jobs, onInspect }: { jobs: Job[]; onInspect: (job: Job) => void }) {
  return (
    <div className="table-wrap">
      <table className="job-table">
        <thead><tr><th scope="col">Job</th><th scope="col">Status</th><th scope="col" className="table-attempts">Attempts</th><th scope="col" className="table-date">Submitted</th><th scope="col"><span className="sr-only">Details</span></th></tr></thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.id}>
              <td><div className="job-cell">
                <span className="job-icon"><FileText size={17} aria-hidden="true" /></span>
                <span><strong>{formatType(job.type)}</strong><code title={job.id}>#{job.id.slice(0, 8)}</code></span>
              </div></td>
              <td><StatusBadge status={job.status} /></td>
              <td className="table-attempts"><span>{job.attempts} / {job.max_attempts}</span></td>
              <td className="table-date"><time dateTime={job.created_at} title={formatTimestamp(job.created_at)}>{formatShortDate(job.created_at)}</time></td>
              <td><button type="button" className="icon-button job-inspect" onClick={() => onInspect(job)} aria-label={`Inspect job ${job.id.slice(0, 8)}`} title="Inspect job"><ChevronRight size={18} aria-hidden="true" /></button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function RecentJobs({ state, onInspect }: {
  state: PollState<JobPage> & { refresh: () => void }
  onInspect: (job: Job) => void
}) {
  return (
    <section className="panel history-panel" aria-labelledby="recent-heading">
      <div className="panel-heading">
        <div><h2 id="recent-heading">Recent jobs</h2><p>Latest submissions and their current status</p></div>
        <a href="#jobs" className="button button-small">View all jobs</a>
      </div>
      <div className="history-error"><ErrorNotice state={state} onRetry={state.refresh} /></div>
      {state.data?.jobs.length ? <JobTable jobs={state.data.jobs} onInspect={onInspect} />
        : state.status === 'loading' ? <Loading label="Loading recent jobs" />
        : state.data ? <EmptyState title="No jobs yet" icon={<Inbox size={22} />}>Submit a word-count job to start monitoring its progress.</EmptyState>
        : null}
    </section>
  )
}

export function JobHistory({ state, refresh, query, onQuery, status, onStatus, page, onPage, onInspect }: {
  state: PollState<JobPage>
  refresh: () => void
  query: string
  onQuery: (query: string) => void
  status: JobStatus | ''
  onStatus: (status: JobStatus | '') => void
  page: number
  onPage: (page: number) => void
  onInspect: (job: Job) => void
}) {
  const total = state.data?.total ?? 0
  const matching = state.data?.jobs.length ?? 0
  const start = page * PAGE_SIZE
  return (
    <section className="panel history-panel" aria-label="Job history">
      <div className="history-tools">
        <label className="search-field">
          <Search size={17} aria-hidden="true" />
          <span className="sr-only">Search jobs by ID or type</span>
          <input type="search" maxLength={100} placeholder="Search by job ID or type" value={query} onChange={(event) => onQuery(event.target.value)} />
        </label>
        <Select aria-label="Filter by status" value={status} onChange={(event) => onStatus(event.target.value as JobStatus | '')}>
          <option value="">All statuses</option>
          {jobStatuses.map((value) => <option key={value} value={value}>{formatType(value)}</option>)}
        </Select>
      </div>
      <div className="history-error"><ErrorNotice state={state} onRetry={refresh} /></div>
      {state.status === 'loading' && <Loading label="Loading job history" />}
      {matching > 0 && <JobTable jobs={state.data!.jobs} onInspect={onInspect} />}
      {state.data && matching === 0 && <EmptyState title="No matching jobs" icon={<Search size={22} />}>
        {query || status ? 'Try another search or status filter.' : 'Submitted jobs will appear here.'}
      </EmptyState>}
      <div className="table-footer">
        <span>{matching > 0 ? `${formatCount(start + 1)}–${formatCount(start + matching)} of ${formatCount(total)} jobs`
          : state.data ? `${formatCount(total)} matching jobs` : 'Job history'}</span>
        <div className="pagination">
          <button type="button" className="icon-button" disabled={page === 0} onClick={() => onPage(page - 1)} aria-label="Previous page"><ChevronLeft size={17} /></button>
          <span>Page {formatCount(page + 1)}</span>
          <button type="button" className="icon-button" disabled={start + PAGE_SIZE >= total} onClick={() => onPage(page + 1)} aria-label="Next page"><ChevronRight size={17} /></button>
        </div>
      </div>
    </section>
  )
}
