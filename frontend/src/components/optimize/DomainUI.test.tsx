import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AssistantBlock } from './AssistantBlock'
import { ConsoleInput } from './ConsoleInput'

afterEach(cleanup)

describe('领域自动路由（2026-11-14：前端无手动选择器，恒自动）', () => {
  it('不渲染任何领域 pill 选择器', () => {
    render(<ConsoleInput isSubmitting={false} projectOptional onSubmit={vi.fn()} />)
    expect(screen.queryByRole('radiogroup')).toBeNull()
    for (const label of ['代码', '工作', '生活', '创意']) {
      expect(screen.queryByRole('radio', { name: label })).toBeNull()
    }
  })
})

describe('领域徽标（AssistantBlock）', () => {
  it('有路由结论时渲染域徽标，fallback 源附加弱提示', () => {
    render(<AssistantBlock domainVerdict={{ domain: 'work', source: 'fallback', confidence: 0 }} />)
    const badge = screen.getByText(/工作/)
    expect(badge.textContent).toContain('已回退')
  })

  it('无路由结论（旧会话）不渲染徽标', () => {
    render(<AssistantBlock />)
    expect(screen.queryByText('工作')).toBeNull()
  })
})
