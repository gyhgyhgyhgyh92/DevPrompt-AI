/**
 * 可观测性导出（2026-11-12）：浏览器端 JSON / CSV 下载，零后端改动、零新依赖。
 *
 * CSV 细节：带 UTF-8 BOM（Excel 打开中文不乱码），字段含逗号/引号/换行时加引号转义。
 */

export type CsvCell = string | number | boolean | null | undefined

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // 部分浏览器在 click 后立刻 revoke 会让下载中断；下一拍释放。
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

/** 文件名：`devprompt-<prefix>-<session8>-<yyyymmdd-hhmmss>.json|csv`。 */
export function exportFilename(
  prefix: string,
  sessionId: string,
  extension: 'json' | 'csv',
): string {
  const short = sessionId.replace(/[^a-zA-Z0-9]/g, '').slice(0, 8) || 'session'
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
  return `devprompt-${prefix}-${short}-${stamp}.${extension}`
}

/** 下载 JSON：结构由调用方决定（带 session_id / exported_at / filters 等元信息）。 */
export function downloadJson(filename: string, data: unknown): void {
  const text = JSON.stringify(data, null, 2)
  triggerDownload(new Blob([text], { type: 'application/json;charset=utf-8' }), filename)
}

function csvCell(value: CsvCell): string {
  if (value === null || value === undefined) return ''
  const text = String(value)
  if (/[",\r\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`
  return text
}

/** 生成 CSV 文本（含 BOM 与 CRLF）；拆出纯函数便于单测，避免 Blob.text() 吞掉 BOM。 */
export function buildCsv(columns: string[], rows: CsvCell[][]): string {
  const lines = [columns.map(csvCell).join(','), ...rows.map((row) => row.map(csvCell).join(','))]
  return `\uFEFF${lines.join('\r\n')}`
}

/** 下载 CSV：首行为列名；单元格自动转义，整体带 BOM。 */
export function downloadCsv(filename: string, columns: string[], rows: CsvCell[][]): void {
  triggerDownload(new Blob([buildCsv(columns, rows)], { type: 'text/csv;charset=utf-8' }), filename)
}
