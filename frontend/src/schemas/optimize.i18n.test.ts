/**
 * 校验文案的多语言（2026-11-06，F-209）。
 *
 * Zod 的 `refine` message 必须写成函数形式才能在每次校验时求值——写成常量会在
 * 模块加载时锁定首次语言（切到英文后仍出中文）。这里钉住「切换语言后 message 跟着变」。
 */
import { afterEach, describe, expect, it } from 'vitest'
import { i18n } from '../i18n'
import { FollowupRequestSchema } from './optimize'

function parseError(): string {
  const result = FollowupRequestSchema.safeParse({
    answers: null,
    escape: true,
    guardrail_action: 'generate',
  })
  expect(result.success).toBe(false)
  return result.error?.issues[0]?.message ?? ''
}

describe('FollowupRequestSchema 校验文案', () => {
  afterEach(() => {
    void i18n.changeLanguage('zh-CN')
  })

  it('默认中文', () => {
    expect(parseError()).toContain('三种模式必须且只能启用一种')
  })

  it('切到英文后即时变英文', () => {
    void i18n.changeLanguage('en')
    expect(parseError()).toContain('Exactly one of')
  })

  it('切回中文仍正确', () => {
    void i18n.changeLanguage('en')
    void i18n.changeLanguage('zh-CN')
    expect(parseError()).toContain('三种模式必须且只能启用一种')
  })
})
