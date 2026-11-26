import { AlertCircle, FileText, LoaderCircle, X } from 'lucide-react'
import { type FormEvent, type ReactNode, useCallback, useEffect, useId, useRef, useState } from 'react'
import { getJobDetails, submitWordCount } from '../api'
import { formatCount, formatDuration, formatTimestamp, formatType } from '../format'
import type { Job } from '../types'
import { usePoll } from '../usePoll'
import { ErrorNotice, Loading, StatusBadge } from './ui'

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
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || text.length === 0) return
    setBusy(true)
    setError('')
    try {
      onSubmitted(await submitWordCount(text))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The job could not be submitted.')
      setBusy(false)
    }
  }

  return (
    <Modal heading="Submit a job" onClose={() => { if (!busy) onClose() }}>
      <form onSubmit={submit}>
        <div className="dialog-content">
          <div className="submission-type"><span className="job-icon"><FileText size={18} /></span><div><strong>Word count</strong><p>Counts whitespace-separated words in your text.</p></div></div>
          <label className="form-label" htmlFor="word-count-text">Text to count</label>
          <textarea id="word-count-text" name="text" required maxLength={100000} rows={6} placeholder="Paste or type your text here…" value={text} onChange={(event) => setText(event.target.value)} />
          <div className="char-count">{formatCount(text.length)} / 100,000 characters</div>
          {error && <p className="inline-error" role="alert"><AlertCircle size={17} />{error}</p>}
        </div>
        <footer className="dialog-actions">
          <button type="button" className="button" disabled={busy} onClick={onClose}>Cancel</button>
          <button type="submit" className="button button-primary" disabled={busy || text.length === 0}>
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
