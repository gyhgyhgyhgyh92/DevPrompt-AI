import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { buildCsv, downloadCsv, downloadJson, exportFilename } from './exportData'

interface Captured {
  blob: Blob
  filename: string
}

let captured: Captured[] = []

beforeEach(() => {
  captured = []
  vi.spyOn(URL, 'createObjectURL').mockImplementation((blob: Blob | MediaSource) => {
    captured.push({ blob: blob as Blob, filename: '' })
    return 'blob:mock'
  })
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    const last = captured[captured.length - 1]
    if (last !== undefined) last.filename = this.download
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('exportData', () => {
  it('downloadJson 生成 JSON Blob 与带时间戳的文件名', async () => {
    downloadJson(exportFilename('session-log', 'abcdef123456', 'json'), { a: 1 })

    expect(captured).toHaveLength(1)
    expect(captured[0]!.filename).toMatch(/^devprompt-session-log-abcdef12-\d{4}-.*\.json$/)
    expect(captured[0]!.blob.type).toContain('application/json')
    expect(await captured[0]!.blob.text()).toBe('{\n  "a": 1\n}')
  })

  it('buildCsv 带 BOM、CRLF，并转义逗号/引号/换行', () => {
    const text = buildCsv(
      ['seq', 'text'],
      [
        [1, 'a,b'],
        [2, 'say "hi"'],
        [3, 'line1\nline2'],
      ],
    )

    expect(text.startsWith('\uFEFF')).toBe(true)
    expect(text).toContain('seq,text')
    expect(text).toContain('1,"a,b"')
    expect(text).toContain('2,"say ""hi"""')
    expect(text).toContain('3,"line1\nline2"')
    expect(text).toContain('\r\n')
  })

  it('downloadCsv 生成 CSV Blob', () => {
    downloadCsv('x.csv', ['a'], [[1]])

    expect(captured[0]!.filename).toBe('x.csv')
    expect(captured[0]!.blob.type).toContain('text/csv')
  })

  it('空值导出为空单元格', () => {
    const text = buildCsv(['a', 'b'], [[null, undefined]])
    expect(text).toContain('a,b\r\n,')
  })
})
