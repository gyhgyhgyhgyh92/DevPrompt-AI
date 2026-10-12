import { describe, expect, it } from 'vitest'

/** MUST-16 违规形态：多字段订阅返回对象字面量（必须改用 useShallow）。 */
const MULTI_FIELD_SELECTOR_RE = /use\w*Store\s*\(\s*\(?\s*\w*\s*\)?\s*=>\s*\(\s*\{/

/**
 * 用 Vite 的 glob 原样读入 src 源码（?raw），
 * 避免在 jsdom 测试环境依赖 node 内置模块类型（本项目不引 @types/node，MUST-04）。
 */
const rawFiles = import.meta.glob('./**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
})

function isSourceText(entry: [string, unknown]): entry is [string, string] {
  return typeof entry[1] === 'string'
}

function isScannedSource(key: string): boolean {
  return !key.endsWith('openapi.generated.ts') && !/\.test\.tsx?$/.test(key)
}

describe('MUST-16 静态检查', () => {
  it('src 下不存在 useStore(s => ({...})) 多字段订阅违规形态', () => {
    const violations = Object.entries(rawFiles)
      .filter(isSourceText)
      .filter(([key, source]) => isScannedSource(key) && MULTI_FIELD_SELECTOR_RE.test(source))
      .map(([key]) => key)

    expect(violations).toEqual([])
  })
})
