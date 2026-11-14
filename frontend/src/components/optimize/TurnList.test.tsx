import { cleanup, render, screen } from '@testing-library/react'
import type { ComponentProps } from 'react'
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
    variants: [
      { title: `方案${index}`, body: `正文${index}`, changes: [], claims: [], fallback: false },
    ],
    facts: [],
  }
}

/** 默认 props：分页与操作条相关项统一走「无更早轮次 / 不继续」的常态。 */
function renderList(
  props: Partial<ComponentProps<typeof TurnList>> & { turns: TurnSummaryPayload[] },
) {
  return render(
    <TurnList
      turns={props.turns}
      loadTurn={props.loadTurn ?? vi.fn()}
      hasMore={props.hasMore ?? false}
      onLoadEarlier={props.onLoadEarlier ?? vi.fn()}
      loadingEarlier={props.loadingEarlier ?? false}
      onContinueFrom={props.onContinueFrom ?? vi.fn()}
      onRollbackTo={props.onRollbackTo ?? vi.fn()}
    />,
  )
}

describe('TurnList 全文流', () => {
  it('无轮次时不渲染', () => {
    const { container } = renderList({ turns: [] })
    expect(container.firstChild).toBeNull()
  })

  it('进入即加载并完整铺开，无需点击', async () => {
    const loadTurn = vi.fn(async () => detail(0))
    renderList({ turns: [summary(0)], loadTurn })

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
    renderList({ turns: [summary(0), summary(1)], loadTurn })

    expect(await screen.findByText('第 1 轮原句')).toBeTruthy()
    expect(await screen.findByText('第 2 轮原句')).toBeTruthy()
    expect(loadTurn.mock.calls.map(([id]) => id)).toEqual(['t0', 't1'])
  })

  it('不再硬顶 20 轮：已加载的轮次全部铺开', async () => {
    const turns = Array.from({ length: 23 }, (_, index) => summary(index))
    renderList({ turns, loadTurn: vi.fn(async () => detail(0)) })

    expect(await screen.findByText('第 23 轮')).toBeTruthy()
    expect(screen.getByText('第 1 轮')).toBeTruthy()
    expect(screen.queryByText(/已省略/)).toBeNull()
  })

  it('有更早轮次时给出加载入口，点击即回调', async () => {
    const onLoadEarlier = vi.fn()
    renderList({
      turns: [summary(0)],
      loadTurn: vi.fn(async () => detail(0)),
      hasMore: true,
      onLoadEarlier,
    })

    const button = await screen.findByRole('button', { name: '加载更早的轮次' })
    button.click()
    expect(onLoadEarlier).toHaveBeenCalledTimes(1)
  })

  it('单轮加载失败只影响该轮', async () => {
    const loadTurn = vi.fn(async (turnId: string) => {
      if (turnId === 't0') throw new Error('boom')
      return detail(1)
    })
    renderList({ turns: [summary(0), summary(1)], loadTurn })

    expect(await screen.findByText(/boom|轮次加载失败/)).toBeTruthy()
    expect(await screen.findByText('第 2 轮原句')).toBeTruthy() // 另一轮不受影响
  })
})
