/**
 * JSX 文案扫描门禁（2026-11-06）。
 *
 * 为什么需要：此前的「清零」只统计引号内的中文字符串，JSX 文本节点
 * （`<p>中文</p>`、独占一行的中文）不加引号、不在口径里，导致 ConfidenceNotice
 * 与另外 30 余处残留被漏计。这里把两种形态都变成断言，防止再次「假清零」。
 *
 * 用 `import.meta.glob`（Vite 原生）读源码，避免依赖 node 类型；
 * 白名单仅语言自称；注释行不参与判定。
 */
import { describe, expect, it } from 'vitest'

const RAW = import.meta.glob('../**/*.tsx', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const HAN = /[\u4e00-\u9fff]/
const INLINE_JSX = />[^<>{}]*[\u4e00-\u9fff][^<>{}]*</
const WHOLE_LINE = /^\s*[\u4e00-\u9fff][^<>{}=;]*$/
const WHITELIST = ['简体中文', 'English']

function offenders(pattern: RegExp): string[] {
  const hits: string[] = []
  for (const [file, content] of Object.entries(RAW)) {
    if (file.includes('.test.')) continue
    let inComment = false
    content.split('\n').forEach((line: string, index: number) => {
      const trimmed = line.trim()
      // 注释不算文案：JS 行注释、块注释续行、JSX 表达式注释 {* … *} 的续行
      if (inComment) {
        if (trimmed.includes('*/')) inComment = false
        return
      }
      if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) return
      if (trimmed.startsWith('{/*')) {
        if (!trimmed.includes('*/')) inComment = true
        return
      }
      if (!HAN.test(line) || !pattern.test(line)) return
      if (WHITELIST.some((allowed) => line.includes(allowed))) return
      hits.push(`${file}:${index + 1}: ${trimmed}`)
    })
  }
  return hits
}

describe('JSX 文案不得残留中文硬编码', () => {
  it('同行 JSX 文本节点（>中文<）为 0', () => {
    expect(offenders(INLINE_JSX)).toEqual([])
  })

  it('独占一行的 JSX 文本节点为 0', () => {
    expect(offenders(WHOLE_LINE)).toEqual([])
  })
})
