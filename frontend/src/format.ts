import type { TimeWindow } from './types'

export const formatCount = new Intl.NumberFormat().format
export const formatTime = (value: string | number) =>
  new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
export const formatTimestamp = (value: string) =>
  new Date(value).toLocaleString([], {
    month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
export const formatShortDate = (value: string) =>
  new Date(value).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
export const formatRate = (value: number | null) =>
  value === null ? '—' : new Intl.NumberFormat(undefined, { style: 'percent', maximumFractionDigits: 1 }).format(value)

export const formatDuration = (value: number | null) => {
  if (value === null) return '—'
  if (value < 1) return `${value.toFixed(2)} ms`
  if (value < 1000) return `${formatCount(Math.round(value))} ms`
  return `${(value / 1000).toFixed(2)} s`
}

export const formatType = (type: string) => {
  if (type === 'csv_sales_summary') return 'CSV sales summary'
  const spaced = type.replaceAll('_', ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}
export const formatBucket = (value: string, window: TimeWindow) =>
  window === '7d' || window === '30d'
    ? new Date(value).toLocaleDateString([], { month: 'short', day: 'numeric' })
    : formatTime(value)
