import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { EmptyState } from './EmptyState'
import { Skeleton } from './Skeleton'
import { Toast } from './Toast'

afterEach(() => {
  cleanup()
})

describe('EmptyState', () => {
  it('text 变体：纯文字形态（Web 现状）', () => {
    render(<EmptyState title="暂无历史会话" />)

    expect(screen.getByText('暂无历史会话')).toBeTruthy()
  })

  it('icon 变体：标题 + 说明 + 图标底座', () => {
    render(
      <EmptyState
        variant="icon"
        icon={<span data-testid="icon">I</span>}
        title="尚无会话"
        description="提交一次优化后此处会实时输出事件流。"
      />,
    )

    expect(screen.getByText('尚无会话')).toBeTruthy()
    expect(screen.getByText('提交一次优化后此处会实时输出事件流。')).toBeTruthy()
    expect(screen.getByTestId('icon')).toBeTruthy()
  })
})

describe('Skeleton', () => {
  it('渲染占位块（装饰性，不进无障碍树）', () => {
    const { container } = render(<Skeleton height="14px" />)

    const node = container.querySelector('span')
    expect(node?.getAttribute('aria-hidden')).toBe('true')
  })
})

describe('Toast', () => {
  it('message 为 null 时不渲染', () => {
    const { container } = render(<Toast message={null} />)

    expect(container.innerHTML).toBe('')
  })

  it('message 非空时渲染 status 区域', () => {
    render(<Toast message="已复制项目路径" />)

    expect(screen.getByRole('status')).toBeTruthy()
    expect(screen.getByText('已复制项目路径')).toBeTruthy()
  })
})
