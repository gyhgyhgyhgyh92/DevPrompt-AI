import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { TurnDetailPayload, TurnSummaryPayload } from '../../api/types'
import { TurnList } from './TurnList'

afterEach(cleanup)

function summary(index: number): TurnSummaryPayload {
  return {
    turn_id: `t${index}`,
    turn_index: index,
    state: 'DONE',
    target: 'SubmitButton',
    conclusion: `第 ${index + 1} 轮结论`,
    open_items: ['对比度待确认'],
    created_at: '',
  }
}

function detail(index: number): TurnDetailPayload {
  return {
    ...summary(index),
    input: `第 ${index + 1} 轮原句`,
    variants: [{ title: `方案${index}`, body: `正文${index}`, level: 'A', changes: [] }],
    facts: [],
  }
}

describe('TurnList 全文流', () => {
  it('无轮次时不渲染', () => {
    const { container } = render(<TurnList turns={[]} loadTurn={vi.fn()} />)
    expect(container.firstChild).toBeNull()
  })

  it('进入即加载并完整铺开，无需点击', async () => {
    const loadTurn = vi.fn(async () => detail(0))
    render(<TurnList turns={[summary(0)]} loadTurn={loadTurn} />)

    // 用户气泡（右）与助手块（左）同时出现
    expect(await screen.findByText('第 1 轮原句')).toBeTruthy()
    expect(screen.getByText('第 1 轮')).toBeTruthy()
    expect(screen.getByText('方案0')).toBeTruthy()
    expect(screen.getByText('正文0')).toBeTruthy()
    expect(screen.getByText(/对比度待确认/)).toBeTruthy()
    expect(loadTurn).toHaveBeenCalledWith('t0')
  })

  it('多轮按时间顺序铺开，各轮独立加载', async () => {
    const loadTurn = vi.fn(async (turnId: string) => detail(Number(turnId.slice(1))))
    render(<TurnList turns={[summary(0), summary(1)]} loadTurn={loadTurn} />)

    expect(await screen.findByText('第 1 轮原句')).toBeTruthy()
    expect(await screen.findByText('第 2 轮原句')).toBeTruthy()
    expect(loadTurn.mock.calls.map(([id]) => id)).toEqual(['t0', 't1'])
  })

  it('超过 20 轮只铺开最近 20 轮并提示省略', () => {
    const turns = Array.from({ length: 23 }, (_, index) => summary(index))
    render(<TurnList turns={turns} loadTurn={vi.fn(async () => detail(0))} />)

    expect(screen.getByText('更早 3 轮已省略')).toBeTruthy()
    expect(screen.getByText('第 23 轮')).toBeTruthy()
    expect(screen.queryByText('第 1 轮')).toBeNull()
  })

  it('单轮加载失败只影响该轮', async () => {
    const loadTurn = vi.fn(async (turnId: string) => {
      if (turnId === 't0') throw new Error('boom')
      return detail(1)
    })
    render(<TurnList turns={[summary(0), summary(1)]} loadTurn={loadTurn} />)

    expect(await screen.findByText(/boom|轮次加载失败/)).toBeTruthy()
    expect(await screen.findByText('第 2 轮原句')).toBeTruthy() // 另一轮不受影响
  })
})
