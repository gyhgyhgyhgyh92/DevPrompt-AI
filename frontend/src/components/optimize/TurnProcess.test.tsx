import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import type { ThinkingItem } from '../../schemas/stream'
import { TurnProcess } from './TurnProcess'

afterEach(cleanup)

const thinking: ThinkingItem[] = [
  { id: 'ev-2', kind: 'text', text: '开始检索', phase: 'RETRIEVING' },
  {
    id: 'ev-3',
    kind: 'action',
    title: '定位符号定义',
    detail: 'rg -n page .',
    scope: '命中 4 行',
    output: 'o1',
    status: 'ok',
    durationMs: 40,
    phase: 'RETRIEVING',
  },
]

describe('TurnProcess（历史轮过程区）', () => {
  it('有事件时间线时默认折叠，展开后渲染阶段账本与工具卡', async () => {
    const user = userEvent.setup()
    render(<TurnProcess thinking={thinking} />)

    expect(document.querySelector('[class*="chat-reply__phases"]')).toBeNull()

    await user.click(screen.getByRole('button', { name: /执行过程 · 1 步/ }))

    expect(document.querySelector('[class*="chat-reply__phases"]')).not.toBeNull()
    expect(document.querySelector('[class*="trace-step"]')).not.toBeNull()
  })

  it('无 thinking 的旧轮回退到步骤列表，单步可展开看说明', async () => {
    const user = userEvent.setup()
    const steps = [
      { action: 'retrieve', outcome: 'ok', duration_ms: 6057, note: '检索并定位目标符号' },
      { action: 'probe', outcome: 'failed', duration_ms: 8356, note: '取证未覆盖按钮' },
    ]
    render(<TurnProcess steps={steps} />)

    expect(screen.queryByText('retrieve')).toBeNull()

    await user.click(screen.getByRole('button', { name: /动作记录 · 2 步/ }))

    expect(screen.getByText('retrieve')).toBeTruthy()
    expect(screen.getByText('6.1s')).toBeTruthy()
    expect(document.querySelector('[class*="turn-steps__row--failed"]')).not.toBeNull()

    await user.click(screen.getByRole('button', { name: /probe/ }))

    expect(screen.getByText('取证未覆盖按钮')).toBeTruthy()
  })

  it('两种数据源都缺失时不渲染（不留空壳）', () => {
    const { container } = render(<TurnProcess />)

    expect(container.firstChild).toBeNull()
  })
})
