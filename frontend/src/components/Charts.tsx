import { Activity, PieChart as PieIcon, Timer } from 'lucide-react'
import { useId } from 'react'
import {
  Area, AreaChart, CartesianGrid, Line, LineChart, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { formatBucket, formatCount, formatDuration, formatRate } from '../format'
import type { Overview, TimeWindow } from '../types'
import { EmptyState } from './ui'

const palette = { submitted: '#a398ff', completed: '#46d9a5', failed: '#fb8298' }
const tick = { fill: '#9da9c2', fontSize: 12 }
const tooltip = { backgroundColor: '#162033', border: '1px solid #344258', borderRadius: '9px' }

export function Throughput({ data, window }: { data: Overview; window: TimeWindow }) {
  const gradient = useId()
  const hasActivity = data.activity.some((row) => row.submitted || row.completed || row.failed)
  return (
    <section className="panel chart-panel" aria-labelledby="throughput-heading">
      <div className="panel-heading">
        <div><h2 id="throughput-heading">Job throughput</h2><p>Submissions and terminal outcomes</p></div>
        <span className="panel-symbol"><Activity size={18} aria-hidden="true" /></span>
      </div>
      <div className="chart-region">
        {hasActivity ? (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data.activity} margin={{ top: 9, right: 10, left: -16, bottom: 3 }} accessibilityLayer>
              <defs>
                <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={palette.submitted} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={palette.submitted} stopOpacity={0.015} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke="#243149" strokeDasharray="3 5" />
              <XAxis dataKey="start" tickFormatter={(value) => formatBucket(value, window)} tick={tick} tickLine={false} axisLine={false} minTickGap={24} tickMargin={10} />
              <YAxis allowDecimals={false} tick={tick} tickLine={false} axisLine={false} tickMargin={8} />
              <Tooltip contentStyle={tooltip} labelStyle={{ color: '#eef1fb' }} labelFormatter={(value) => formatBucket(String(value), window)} />
              <Area type="monotone" dataKey="submitted" name="Submitted" stroke={palette.submitted} strokeWidth={2.5} fill={`url(#${gradient})`} isAnimationActive={false} />
              <Area type="monotone" dataKey="completed" name="Completed" stroke={palette.completed} strokeWidth={2} fill="none" isAnimationActive={false} />
              <Area type="monotone" dataKey="failed" name="Failed" stroke={palette.failed} strokeWidth={2} fill="none" isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="empty-chart"><EmptyState title="No activity in this range" icon={<Activity size={20} />}>New submissions and outcomes will appear here.</EmptyState></div>
        )}
      </div>
      <div className="chart-legend" aria-label="Period totals">
        {(['submitted', 'completed', 'failed'] as const).map((key) => (
          <span key={key}><i style={{ background: palette[key] }} />{key}<strong>{formatCount(data.period[key])}</strong></span>
        ))}
      </div>
    </section>
  )
}

export function Outcomes({ period }: { period: Overview['period'] }) {
  const slices = [
    { name: 'Completed', value: period.completed, fill: palette.completed },
    { name: 'Failed', value: period.failed, fill: palette.failed },
  ]
  return (
    <section className="panel outcome-panel" aria-labelledby="outcomes-heading">
      <div className="panel-heading">
        <div><h2 id="outcomes-heading">Job outcomes</h2><p>Terminal jobs in this range</p></div>
        <span className="panel-symbol"><PieIcon size={18} aria-hidden="true" /></span>
      </div>
      <div className="donut">
        {period.success_rate !== null && (
          <div className="donut-chart" aria-hidden="true">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={slices} dataKey="value" innerRadius={49} outerRadius={61} startAngle={90} endAngle={-270} stroke="none" isAnimationActive={false} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}
        <div className="donut-caption">
          <strong>{formatRate(period.success_rate)}</strong>
          <span>Success rate</span>
        </div>
      </div>
      <div className="outcome-breakdown">
        <div><span><i style={{ background: palette.completed }} />Completed</span><strong>{formatCount(period.completed)}</strong></div>
        <div><span><i style={{ background: palette.failed }} />Failed</span><strong>{formatCount(period.failed)}<small>{formatRate(period.failure_rate)}</small></strong></div>
      </div>
      <div className="outcome-duration">
        <span><Timer size={15} aria-hidden="true" />Avg. processing</span>
        <strong title={`${period.duration.samples} measured attempts`}>{formatDuration(period.duration.average_ms)}</strong>
      </div>
    </section>
  )
}

export function CompletionChart({ data, window }: { data: Overview; window: TimeWindow }) {
  const rates = data.activity.map((point) => ({
    start: point.start,
    rate: point.completed + point.failed ? point.completed / (point.completed + point.failed) : null,
  }))
  return (
    <section className="panel chart-panel" aria-labelledby="rate-heading">
      <div className="panel-heading">
        <div><h2 id="rate-heading">Completion rate</h2><p>Successful jobs as a share of terminal jobs</p></div>
        <strong className="chart-value">{formatRate(data.period.success_rate)}</strong>
      </div>
      <div className="chart-region">
        {data.period.success_rate === null ? (
          <div className="empty-chart"><EmptyState title="No terminal jobs in this range" icon={<Activity size={20} />} /></div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rates} margin={{ top: 9, right: 10, left: -8, bottom: 3 }} accessibilityLayer>
              <CartesianGrid vertical={false} stroke="#243149" strokeDasharray="3 5" />
              <XAxis dataKey="start" tickFormatter={(value) => formatBucket(value, window)} tick={tick} tickLine={false} axisLine={false} minTickGap={24} tickMargin={10} />
              <YAxis domain={[0, 1]} tickFormatter={formatRate} tick={tick} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltip} labelStyle={{ color: '#eef1fb' }} labelFormatter={(value) => formatBucket(String(value), window)} formatter={(value) => formatRate(Number(value))} />
              <Line dataKey="rate" name="Completion rate" stroke={palette.completed} strokeWidth={2.5} dot={{ r: 3 }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  )
}
