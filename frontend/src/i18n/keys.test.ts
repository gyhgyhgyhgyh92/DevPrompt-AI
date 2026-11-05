/**
 * i18n 字典质量守卫（2026-11-06 多语言）。
 *
 * 两份语言包必须键集合完全一致、叶子值非空——防止「只翻了界面没翻错误码」
 * 这类半成品悄悄上线；错误码键还必须覆盖 schemas/errorCodes.ts 的全部码
 * （与 scripts/check_architecture.py 第 7 项互为两面：那边查「码→键」，
 * 这里查「键→文案」）。
 */
import { describe, expect, it } from 'vitest'
import en from './locales/en.json'
import zhCN from './locales/zh-CN.json'
import { ERROR_TEXT } from '../schemas/errorCodes'

type Dict = Record<string, unknown>

function leafKeys(dict: Dict, prefix = ''): string[] {
  return Object.entries(dict).flatMap(([key, value]) => {
    const path = prefix === '' ? key : `${prefix}.${key}`
    return typeof value === 'object' && value !== null ? leafKeys(value as Dict, path) : [path]
  })
}

function leafValues(dict: Dict, prefix = ''): string[] {
  return Object.entries(dict).flatMap(([key, value]) => {
    const path = prefix === '' ? key : `${prefix}.${key}`
    return typeof value === 'object' && value !== null
      ? leafValues(value as Dict, path)
      : [value as string]
  })
}

const zhKeys = leafKeys(zhCN).sort()
const enKeys = leafKeys(en).sort()

describe('i18n 字典质量', () => {
  it('zh-CN 与 en 键集合完全一致', () => {
    expect(enKeys).toEqual(zhKeys)
  })

  it('两份字典的叶子值都非空字符串', () => {
    for (const values of [leafValues(zhCN), leafValues(en)]) {
      for (const value of values) {
        expect(typeof value, `键值必须是字符串：${value}`).toBe('string')
        expect(value.trim(), `存在空文案：${value}`).not.toBe('')
      }
    }
  })

  it('errorCodes.ts 的每个码在字典里都有 errors.<code> 文案', () => {
    const errorsDict = (zhCN as Dict).errors as Record<string, string> | undefined
    const missing = Object.keys(ERROR_TEXT).filter((code) => errorsDict?.[code] === undefined)
    expect(missing, `语言包缺错误码文案：${missing.join(', ')}`).toEqual([])
  })
})
