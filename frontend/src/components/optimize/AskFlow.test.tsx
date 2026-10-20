import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { UnknownItemPayload } from '../../api/types'
import { AskFlow } from './AskFlow'

afterEach(() => {
  cleanup()
  document.body.style.overflow = ''
})

const QUESTIONS: UnknownItemPayload[] = [
  {
    key: 'scope',
    reason: '范围不明',
    best_guess: '',
    ask: '改动范围？',
    header: '范围',
    options: [{ label: '只改一处', description: '' }],
    multi_select: false,
  },
  {
    key: 'tests',
    reason: '无测试文件',
    best_guess: '',
    ask: '要补测试吗？',
    header: '测试',
    options: [{ label: '补测试', description: '' }],
    multi_select: false,
  },
]

function renderFlow(overrides: Partial<Parameters<typeof AskFlow>[0]> = {}) {
  const onSubmitAnswers = vi.fn()
  const onEscape = vi.fn()
  render(
    <AskFlow
      questions={QUESTIONS}
      cleared={[]}
      status="ask"
      isBusy={false}
      onSubmitAnswers={onSubmitAnswers}
      onEscape={onEscape}
      onGuardrail={vi.fn()}
      {...overrides}
    />,
  )
  return { onSubmitAnswers, onEscape }
}

describe('AskFlow 组合层', () => {
  it('弹层打开并显示 0 / 2 已答', () => {
    renderFlow()
    expect(screen.getByText('需要你确认 2 个问题')).toBeTruthy()
    expect(screen.getByText('0 / 2 已答')).toBeTruthy()
  })

  it('作答后计数实时更新', async () => {
    const user = userEvent.setup()
    renderFlow()

    await user.click(screen.getByRole('button', { name: /只改一处/ }))

    expect(screen.getByText('1 / 2 已答')).toBeTruthy()
  })

  it('提交把草稿整份交给上层', async () => {
    const user = userEvent.setup()
    const { onSubmitAnswers } = renderFlow()

    await user.click(screen.getByRole('button', { name: /只改一处/ }))
    const inputs = screen.getAllByPlaceholderText('输入自定义回答...')
    const second = inputs[1]
    if (second === undefined) throw new Error('缺少第二个输入框')
    await user.type(second, '补一个用例')
    await user.click(screen.getByRole('button', { name: '提交' }))

    expect(onSubmitAnswers).toHaveBeenCalledWith({
      scope: '只改一处',
      tests: '补一个用例',
    })
  })

  it('软护栏态改用裁决标题', () => {
    renderFlow({ status: 'guardrail', cleared: ['scope'] })
    expect(screen.getByText(/软护栏：已澄清 1 项/)).toBeTruthy()
  })

  it('Esc 走逃生', async () => {
    const { onEscape } = renderFlow()
    await userEvent.setup().keyboard('{Escape}')
    expect(onEscape).toHaveBeenCalled()
  })
})
