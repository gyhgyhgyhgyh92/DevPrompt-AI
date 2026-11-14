/** 可观测性展示格式化（纯前端展示口径，不含业务判定）。 */

export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (value < 1000) return `${value} ms`
  return `${(value / 1000).toFixed(1)} s`
}

export function formatTimestamp(ts: string): string {
  return ts.trim() === '' ? '—' : ts
}
