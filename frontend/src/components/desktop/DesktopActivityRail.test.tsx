import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DesktopActivityRail } from './DesktopActivityRail'

function renderRail(initialPath = '/', onOpenSettings = vi.fn()) {
  const utils = render(
    <MemoryRouter initialEntries={[initialPath]}>
      <DesktopActivityRail onOpenSettings={onOpenSettings} />
    </MemoryRouter>,
  )
  return { ...utils, onOpenSettings }
}

afterEach(() => {
  cleanup()
})

describe('DesktopActivityRail', () => {
  it('渲染三个路由入口与设置入口', () => {
    renderRail()

    expect(screen.getByRole('navigation', { name: '桌面导航' })).toBeTruthy()
    expect(screen.getByRole('link', { name: '对话' })).toBeTruthy()
    expect(screen.getByRole('link', { name: '历史' })).toBeTruthy()
    expect(screen.getByRole('link', { name: '可观测性' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '设置' })).toBeTruthy()
  })

  it('当前路由项带激活标记，其余不带', () => {
    renderRail('/history')

    expect(screen.getByRole('link', { name: '历史' }).getAttribute('aria-current')).toBe('page')
    expect(screen.getByRole('link', { name: '对话' }).getAttribute('aria-current')).toBeNull()
  })

  it('点击设置入口调用回调（设置不是路由）', async () => {
    const user = userEvent.setup()
    const { onOpenSettings } = renderRail('/')

    await user.click(screen.getByRole('button', { name: '设置' }))

    expect(onOpenSettings).toHaveBeenCalledTimes(1)
  })
})
