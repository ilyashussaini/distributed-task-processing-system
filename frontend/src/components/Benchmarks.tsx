import { Activity } from 'lucide-react'
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import measurements from '../data/benchmark-results.json'
import { formatCount, formatDuration, formatRate, formatShortDate } from '../format'

const points = measurements.configurations.map(({ replicas, summary }) => ({
  workers: String(replicas),
  rate: summary.jobs_per_second,
  p50: summary.end_to_end_ms.p50,
  p95: summary.end_to_end_ms.p95,
  p99: summary.end_to_end_ms.p99,
}))
const tick = { fill: '#9da9c2', fontSize: 12 }
const tooltip = {
  backgroundColor: '#162033', border: '1px solid #344258', borderRadius: '9px', color: '#eef1fb',
}
const tiers = [
  { key: 'p50', color: '#a398ff' },
  { key: 'p95', color: '#46d9a5' },
  { key: 'p99', color: '#fb8298' },
] as const

export default function Benchmarks() {
  const { workload, environment } = measurements
  return (
    <section className="panel benchmark-panel" aria-labelledby="benchmark-heading">
      <div className="panel-heading">
        <div>
          <h2 id="benchmark-heading">Worker scaling benchmark</h2>
          <p>Recorded {formatShortDate(measurements.recorded_at)} · {formatCount(workload.jobs_per_run)} jobs per burst · {formatCount(workload.rows_per_file)} CSV rows per job</p>
        </div>
        <span className="panel-symbol"><Activity size={18} aria-hidden="true" /></span>
      </div>
      <div className="benchmark-charts">
        <figure aria-labelledby="benchmark-throughput">
          <figcaption id="benchmark-throughput">Processed jobs per second</figcaption>
          <div className="chart-region">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={points} margin={{ top: 8, left: -15, right: 20, bottom: 5 }} accessibilityLayer>
                <CartesianGrid vertical={false} stroke="#243149" strokeDasharray="3 5" />
                <XAxis dataKey="workers" tick={tick} tickLine={false} axisLine={false} tickFormatter={(workers) => `${workers}w`} />
                <YAxis tick={tick} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={tooltip} labelFormatter={(workers) => `${workers} workers`} />
                <Line type="linear" dataKey="rate" name="Jobs/s" stroke="#a398ff" strokeWidth={2.5} dot={{ r: 5 }} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </figure>
        <figure aria-labelledby="benchmark-latency">
          <figcaption id="benchmark-latency">End-to-end latency</figcaption>
          <div className="chart-region">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={points} margin={{ top: 8, left: -3, right: 20, bottom: 5 }} accessibilityLayer>
                <CartesianGrid vertical={false} stroke="#243149" strokeDasharray="3 5" />
                <XAxis dataKey="workers" tick={tick} tickLine={false} axisLine={false} tickFormatter={(workers) => `${workers}w`} />
                <YAxis tick={tick} tickLine={false} axisLine={false} tickFormatter={(ms) => `${ms / 1000}s`} />
                <Tooltip contentStyle={tooltip} labelFormatter={(workers) => `${workers} workers`} formatter={(value) => formatDuration(Number(value))} />
                {tiers.map(({ key, color }) => <Line key={key} type="linear" name={key} dataKey={key} stroke={color} strokeWidth={2} dot={{ r: 4 }} isAnimationActive={false} />)}
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="chart-legend">{tiers.map(({ key, color }) => <span key={key}><i style={{ background: color }} />{key}</span>)}</div>
        </figure>
      </div>
      <div className="table-wrap" role="region" tabIndex={0} aria-label="Benchmark measurements">
        <table className="job-table benchmark-table">
          <thead><tr><th scope="col">Workers</th><th scope="col">Jobs/s</th><th scope="col">E2E p50</th><th scope="col">E2E p95</th><th scope="col">E2E p99</th><th scope="col">Queue p95</th><th scope="col">Failure rate</th></tr></thead>
          <tbody>{measurements.configurations.map(({ replicas, summary }) => <tr key={replicas}>
            <th scope="row">{replicas}</th>
            <td>{summary.jobs_per_second?.toFixed(2) ?? '—'}</td>
            <td>{formatDuration(summary.end_to_end_ms.p50)}</td>
            <td>{formatDuration(summary.end_to_end_ms.p95)}</td>
            <td>{formatDuration(summary.end_to_end_ms.p99)}</td>
            <td>{formatDuration(summary.queue_wait_ms.p95)}</td>
            <td>{formatRate(summary.failure_rate)}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <p className="benchmark-environment">{workload.repetitions} runs per configuration · {environment.cpu_model} · Docker reported {environment.docker_cpus} CPUs</p>
    </section>
  )
}
