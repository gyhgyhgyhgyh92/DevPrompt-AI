import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AgentTimeline, formatElapsed } from './AgentTimeline'

describe('AgentTimeline', () => {
  it('渲染动作标签、步数与耗时', () => {
    render(<AgentTimeline step={3} action="generate" elapsedMs={1500} />)

    expect(screen.getByText('生成方案')).toBeTruthy()
    expect(screen.getByText('第 3 步')).toBeTruthy()
    expect(screen.getByText('1.5 s')).toBeTruthy()
  })

  it('非运行态（三个字段全空）不渲染', () => {
    const { container } = render(<AgentTimeline step={null} action={null} elapsedMs={null} />)

    expect(container.firstChild).toBeNull()
  })

  it('未知动作名原样展示，不吞掉信息', () => {
    render(<AgentTimeline step={1} action="unknown_action" elapsedMs={null} />)

    expect(screen.getByText('unknown_action')).toBeTruthy()
  })

  it('动作名为空时显示「决策中」', () => {
    render(<AgentTimeline step={0} action={null} elapsedMs={null} />)

    expect(screen.getByText('决策中')).toBeTruthy()
  })
})

describe('formatElapsed', () => {
  it('不足一秒保留毫秒', () => {
    expect(formatElapsed(320)).toBe('320 ms')
  })

  it('满一秒保留一位小数秒', () => {
    expect(formatElapsed(1000)).toBe('1.0 s')
    expect(formatElapsed(15600)).toBe('15.6 s')
  })
})
