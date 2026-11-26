import { AlertCircle, FileText, LoaderCircle, X } from 'lucide-react'
import { type FormEvent, type ReactNode, useCallback, useEffect, useId, useRef, useState } from 'react'
import { getJobDetails, submitCsv, submitWordCount } from '../api'
import { formatCount, formatDuration, formatTimestamp, formatType } from '../format'
import type { Job } from '../types'
import { usePoll } from '../usePoll'
import { ErrorNotice, Loading, Select, StatusBadge } from './ui'

const csvLimit = 512 * 1024

function Modal({ heading, onClose, drawer = false, children }: {
  heading: string
  onClose: () => void
  drawer?: boolean
  children: ReactNode
}) {
  const label = useId()
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = ref.current!
    dialog.showModal()
    return () => { if (dialog.open) dialog.close() }
  }, [])

  return (
    <dialog ref={ref} className={drawer ? 'dialog drawer' : 'dialog'} aria-labelledby={label}
      onCancel={(event) => { event.preventDefault(); onClose() }}>
      <header className="dialog-heading">
        <h2 id={label}>{heading}</h2>
        <button type="button" className="icon-button" aria-label="Close dialog" onClick={onClose}><X size={19} /></button>
      </header>
      {children}
    </dialog>
  )
}

export function SubmitDialog({ onClose, onSubmitted }: { onClose: () => void; onSubmitted: (job: Job) => void }) {
  const [type, setType] = useState('word_count')
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const csv = type === 'csv_sales_summary'
  const fileError = file && (file.size === 0 ? 'Choose a nonempty CSV file.'
    : file.size > csvLimit ? 'The CSV file exceeds 512 KiB.' : '')
  const valid = csv ? file !== null && !fileError : text.length > 0

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !valid) return
    setBusy(true)
    setError('')
    try {
      const job = csv && file ? await submitCsv(file) : await submitWordCount(text)
      onSubmitted(job)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The job could not be submitted.')
      setBusy(false)
    }
  }

  return (
    <Modal heading="Submit a job" onClose={() => { if (!busy) onClose() }}>
      <form onSubmit={submit}>
        <div className="dialog-content">
          <div className="submission-type">
            <label className="form-label" htmlFor="submission-job-type">Job type</label>
            <Select id="submission-job-type" value={type} disabled={busy} onChange={(event) => {
              setType(event.target.value); setError(''); setFile(null)
            }}>
              <option value="word_count">Word count</option>
              <option value="csv_sales_summary">CSV sales summary</option>
            </Select>
          </div>
          {csv ? <>
            <label className="form-label" htmlFor="sales-csv">Sales CSV file</label>
            <input className="csv-file" id="sales-csv" type="file" accept=".csv,text/csv" required aria-describedby="csv-help"
              onChange={(event) => { setError(''); setFile(event.target.files?.[0] ?? null) }} />
            <p className="field-help" id="csv-help">UTF-8, up to 512 KiB and 10,000 rows. Include <code>order_id</code>, <code>region</code>, <code>quantity</code>, and <code>unit_price</code>.</p>
            {fileError && <p className="inline-error" role="alert"><AlertCircle size={17} />{fileError}</p>}
          </> : <>
            <label className="form-label" htmlFor="word-count-text">Text to count</label>
            <textarea id="word-count-text" name="text" required maxLength={100000} rows={6} placeholder="Paste or type your text here…" value={text} onChange={(event) => setText(event.target.value)} />
            <div className="char-count">{formatCount(text.length)} / 100,000 characters</div>
          </>}
          {error && <p className="inline-error" role="alert"><AlertCircle size={17} />{error}</p>}
        </div>
        <footer className="dialog-actions">
          <button type="button" className="button" disabled={busy} onClick={onClose}>Cancel</button>
          <button type="submit" className="button button-primary" disabled={busy || !valid}>
            {busy && <LoaderCircle size={16} className="animate-spin" />}{busy ? 'Submitting' : 'Submit job'}
          </button>
        </footer>
      </form>
    </Modal>
  )
}

function DateValue({ date }: { date: string | null }) {
  return date ? <time dateTime={date}>{formatTimestamp(date)}</time> : '—'
}

interface SalesRegion {
  region: string
  orders: number
  units_sold: number
  revenue: string
}

function CsvResult({ result }: { result: Record<string, unknown> }) {
  if (
    typeof result.orders !== 'number' || typeof result.units_sold !== 'number'
    || typeof result.revenue !== 'string' || typeof result.average_order_value !== 'string'
    || !Array.isArray(result.regions)
  ) return <pre>{JSON.stringify(result, null, 2)}</pre>

  const regions = result.regions as SalesRegion[]
  return <>
    <dl className="csv-summary">
      <div><dt>Orders</dt><dd>{formatCount(result.orders)}</dd></div>
      <div><dt>Units sold</dt><dd>{formatCount(result.units_sold)}</dd></div>
      <div><dt>Revenue</dt><dd>{result.revenue}</dd></div>
      <div><dt>Average order value</dt><dd>{result.average_order_value}</dd></div>
    </dl>
    <div className="table-wrap csv-breakdown" tabIndex={0} role="region" aria-label="Sales by region">
      <table className="job-table"><thead><tr>
        <th scope="col">Region</th><th scope="col">Orders</th><th scope="col">Units</th><th scope="col">Revenue</th>
      </tr></thead><tbody>{regions.map((region) => <tr key={region.region}>
        <td>{region.region}</td><td>{formatCount(region.orders)}</td><td>{formatCount(region.units_sold)}</td><td>{region.revenue}</td>
      </tr>)}</tbody></table>
    </div>
  </>
}

export function JobDetails({ initial, onClose }: { initial: Job; onClose: () => void }) {
  const load = useCallback((signal: AbortSignal) => getJobDetails(initial.id, signal), [initial.id])
  const state = usePoll(initial.id, load)
  const job = state.data?.job ?? initial
  const attempts = state.data?.attempts
  const wordCount = job.type === 'word_count' && typeof job.result?.word_count === 'number' ? job.result.word_count : null

  return (
    <Modal heading="Job details" onClose={onClose} drawer>
      <div className="dialog-content detail-content">
        <ErrorNotice state={state} onRetry={state.refresh} />
        <div className="detail-intro">
          <span className="job-icon"><FileText size={22} /></span>
          <div><h3>{formatType(job.type)}</h3><code>{job.id}</code></div>
          <span aria-live="polite"><StatusBadge status={job.status} /></span>
        </div>
        <dl className="detail-fields">
          <div><dt>Submitted</dt><dd><DateValue date={job.created_at} /></dd></div>
          <div><dt>Finished</dt><dd><DateValue date={job.completed_at} /></dd></div>
          <div><dt>Attempts started</dt><dd>{job.attempts} of {job.max_attempts}</dd></div>
          <div><dt>Retries started</dt><dd>{Math.max(0, job.attempts - 1)}</dd></div>
          {job.status === 'pending' && job.attempts > 0 && <div><dt>Next retry</dt><dd><DateValue date={job.next_attempt_at} /></dd></div>}
        </dl>
        {job.error && <section className="detail-section error-detail"><h3><AlertCircle size={16} />Last error</h3><p>{job.error}</p></section>}
        {job.result && <section className="detail-section">
          <h3>Result</h3>
          {wordCount !== null ? <p className="result-value"><strong>{formatCount(wordCount)}</strong> {wordCount === 1 ? 'word' : 'words'}</p>
            : job.type === 'csv_sales_summary' ? <CsvResult result={job.result} />
            : <pre>{JSON.stringify(job.result, null, 2)}</pre>}
        </section>}
        <section className="detail-section">
          <h3>Attempt history</h3>
          {state.status === 'loading' && <Loading label="Loading attempts" />}
          {attempts?.length === 0 && <p>{job.attempts === 0 ? 'No attempt has started.' : 'No recorded attempt history for this job.'}</p>}
          {!!attempts?.length && <ol className="attempt-list">
            {attempts.map((attempt) => (
              <li key={attempt.number}>
                <div><strong>Attempt {attempt.number}</strong><StatusBadge status={attempt.status} /></div>
                <dl>
                  <div><dt>Started</dt><dd><DateValue date={attempt.started_at} /></dd></div>
                  <div><dt>Finished</dt><dd><DateValue date={attempt.finished_at} /></dd></div>
                  <div><dt>Duration</dt><dd>{formatDuration(attempt.duration_ms)}</dd></div>
                </dl>
                {attempt.error && <p className="attempt-error">{attempt.error}</p>}
              </li>
            ))}
          </ol>}
        </section>
      </div>
    </Modal>
  )
}
