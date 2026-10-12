import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { UnknownItemPayload } from '../../api/types'
import { FollowupForm } from './FollowupForm'

const questions: UnknownItemPayload[] = [
  { key: 'target', reason: '缺目标定位', best_guess: 'build()', ask: '改哪里？' },
  { key: 'scope', reason: '缺改造范围', best_guess: '仅首页', ask: '改多大范围？' },
]

function renderForm(overrides: Partial<Parameters<typeof FollowupForm>[0]> = {}) {
  const handlers = {
    onSubmitAnswers: vi.fn(),
    onEscape: vi.fn(),
    onGuardrail: vi.fn(),
    ...overrides,
  }
  render(
    <FollowupForm
      questions={questions}
      cleared={['lang']}
      status="ask"
      isBusy={false}
      {...handlers}
    />,
  )
  return handlers
}

afterEach(cleanup)

describe('FollowupForm 反问表单（MUST-26）', () => {
  it('渲染澄清卡 ×N（key 徽章 + reason + best_guess）与已澄清 chips', () => {
    renderForm()

    expect(screen.getByText('target')).toBeTruthy()
    expect(screen.getByText('scope')).toBeTruthy()
    expect(screen.getByText('缺目标定位')).toBeTruthy()
    expect(screen.getByText('缺改造范围')).toBeTruthy()
    expect(screen.getByText(/当前最佳推断：build\(\)/)).toBeTruthy()
    expect(screen.getByText('lang')).toBeTruthy()
  })

  it('「采用推断」把 best_guess 一键填入答复框', async () => {
    const user = userEvent.setup()
    renderForm()

    await user.click(screen.getAllByRole('button', { name: '采用推断' })[0] as HTMLElement)

    const inputs = screen.getAllByRole('textbox', { name: '答复' })
    expect((inputs[0] as HTMLInputElement).value).toBe('build()')
  })

  it('批量答复一次提交全部答复（answers 模式）', async () => {
    const user = userEvent.setup()
    const handlers = renderForm()

    const inputs = screen.getAllByRole('textbox', { name: '答复' })
    await user.type(inputs[0] as HTMLInputElement, 'build()')
    await user.type(inputs[1] as HTMLInputElement, '仅首页')
    await user.click(screen.getByRole('button', { name: '提交答复' }))

    expect(handlers.onSubmitAnswers).toHaveBeenCalledWith({ target: 'build()', scope: '仅首页' })
  })

  it('逃生按钮常驻并以 escape 模式回调', async () => {
    const user = userEvent.setup()
    const handlers = renderForm()

    await user.click(screen.getByRole('button', { name: /直接生成（A 保守版/ }))

    expect(handlers.onEscape).toHaveBeenCalledTimes(1)
  })

  it('guardrail 状态显示裁决面板（继续追问 / 直接生成）', async () => {
    const user = userEvent.setup()
    const handlers = renderForm({ status: 'guardrail' })

    expect(screen.getByText(/软护栏触发/)).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '继续追问' }))
    await user.click(screen.getByRole('button', { name: '直接生成' }))

    expect(handlers.onGuardrail).toHaveBeenNthCalledWith(1, 'continue')
    expect(handlers.onGuardrail).toHaveBeenNthCalledWith(2, 'generate')
  })

  it('提交中禁用全部按钮（MUST-15 禁重试靠禁用）', () => {
    renderForm({ isBusy: true })

    expect((screen.getByRole('button', { name: '提交答复' }) as HTMLButtonElement).disabled).toBe(
      true,
    )
    expect(
      (screen.getByRole('button', { name: /直接生成（A 保守版/ }) as HTMLButtonElement).disabled,
    ).toBe(true)
  })
})
