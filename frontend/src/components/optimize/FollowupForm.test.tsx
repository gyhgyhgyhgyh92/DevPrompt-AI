import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { UnknownItemPayload } from '../../api/types'
import { FollowupForm } from './FollowupForm'

afterEach(cleanup)

const QUESTIONS: UnknownItemPayload[] = [
  {
    key: 'target',
    reason: '缺目标定位',
    best_guess: 'build()',
    ask: '改哪里？',
    header: '',
    options: [],
    multi_select: false,
  },
]

const WITH_OPTIONS: UnknownItemPayload[] = [
  {
    key: 'test_file_exists',
    reason: '未找到关联测试文件',
    best_guess: '',
    ask: '要新建测试文件吗？',
    header: '测试',
    options: [
      { label: '新建同目录', description: '与被测文件同级' },
      { label: '放 __tests__', description: '集中存放' },
    ],
    multi_select: false,
  },
]

const MULTI: UnknownItemPayload[] = [
  {
    key: 'has_state_styles',
    reason: '未见多状态样式',
    best_guess: '',
    ask: '要覆盖哪些状态？',
    header: '状态',
    options: [
      { label: 'hover', description: '' },
      { label: 'focus', description: '' },
    ],
    multi_select: true,
  },
]

interface HarnessProps {
  questions: UnknownItemPayload[]
  cleared?: string[]
  status?: string | null
  isBusy?: boolean
  initial?: Record<string, string>
  onGuardrail?: (action: 'continue' | 'generate') => void
}

/** 受控包装：草稿在 AskFlow 里，测试用局部 state 模拟。 */
function Harness({
  questions,
  cleared = [],
  status = 'ask',
  isBusy = false,
  initial = {},
  onGuardrail = vi.fn(),
}: HarnessProps) {
  const [answers, setAnswers] = useState<Record<string, string>>(initial)
  return (
    <FollowupForm
      questions={questions}
      cleared={cleared}
      status={status}
      isBusy={isBusy}
      answers={answers}
      onAnswersChange={setAnswers}
      onGuardrail={onGuardrail}
    />
  )
}

describe('FollowupForm 问题区', () => {
  it('渲染 header / 问题 / 原因 / 选项说明', () => {
    render(<Harness questions={WITH_OPTIONS} />)

    expect(screen.getByText('测试')).toBeTruthy()
    expect(screen.getByText('要新建测试文件吗？')).toBeTruthy()
    expect(screen.getByText('未找到关联测试文件')).toBeTruthy()
    expect(screen.getByText('与被测文件同级')).toBeTruthy()
    expect(screen.getByText('单选')).toBeTruthy()
  })

  it('单选点选即替换，再点另一项切换', async () => {
    const user = userEvent.setup()
    render(<Harness questions={WITH_OPTIONS} />)

    await user.click(screen.getByRole('button', { name: /新建同目录/ }))
    expect(screen.getByRole('button', { name: /新建同目录/ }).getAttribute('aria-pressed')).toBe(
      'true',
    )

    await user.click(screen.getByRole('button', { name: /放 __tests__/ }))
    expect(screen.getByRole('button', { name: /新建同目录/ }).getAttribute('aria-pressed')).toBe(
      'false',
    )
    expect(screen.getByRole('button', { name: /放 __tests__/ }).getAttribute('aria-pressed')).toBe(
      'true',
    )
  })

  it('多选可叠加与取消，值用 ", " 拼接', async () => {
    const user = userEvent.setup()
    render(<Harness questions={MULTI} />)

    await user.click(screen.getByRole('button', { name: /hover/ }))
    await user.click(screen.getByRole('button', { name: /focus/ }))

    const input = screen.getByPlaceholderText('输入自定义回答...') as HTMLInputElement
    expect(input.value).toBe('hover, focus')

    await user.click(screen.getByRole('button', { name: /hover/ }))
    expect(input.value).toBe('focus')
  })

  it('自由输入可覆盖选项结果', async () => {
    const user = userEvent.setup()
    render(<Harness questions={WITH_OPTIONS} />)

    await user.click(screen.getByRole('button', { name: /新建同目录/ }))
    const input = screen.getByPlaceholderText('输入自定义回答...')
    await user.clear(input)
    await user.type(input, '放 src/__tests__')

    expect((input as HTMLInputElement).value).toBe('放 src/__tests__')
  })

  it('「采用推断」一键填入 best_guess', async () => {
    const user = userEvent.setup()
    render(<Harness questions={QUESTIONS} />)

    await user.click(screen.getByRole('button', { name: '采用推断' }))

    expect((screen.getByPlaceholderText('输入自定义回答...') as HTMLInputElement).value).toBe(
      'build()',
    )
  })

  it('软护栏状态显示裁决面板', async () => {
    const onGuardrail = vi.fn()
    const user = userEvent.setup()
    render(
      <Harness questions={[]} status="guardrail" cleared={['target']} onGuardrail={onGuardrail} />,
    )

    expect(screen.getByText(/软护栏触发/)).toBeTruthy()
    await user.click(screen.getByRole('button', { name: '继续追问' }))
    expect(onGuardrail).toHaveBeenCalledWith('continue')
  })

  it('已澄清清单以 chip 展示', () => {
    render(<Harness questions={QUESTIONS} cleared={['target', 'scope']} />)
    expect(screen.getByText('已澄清：')).toBeTruthy()
    expect(screen.getByText('scope')).toBeTruthy()
  })

  it('提交中禁用选项与采用推断', () => {
    render(<Harness questions={QUESTIONS} isBusy />)
    expect(screen.getByRole('button', { name: '采用推断' }).hasAttribute('disabled')).toBe(true)
  })
})
