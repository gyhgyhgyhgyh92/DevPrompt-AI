import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { useOptimizeStore } from './stores/useOptimizeStore'
import { usePreferenceStore } from './stores/usePreferenceStore'

function jsonResponse(payload: unknown) {
  return { status: 200, headers: { get: () => null }, json: async () => payload }
}

/** 所有请求返回成功空载荷（App 壳层只关心 /health 与 /history，其余保持空态）。 */
function stubFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => jsonResponse({ code: 0, message: 'ok', request_id: 'rid', data: null })),
  )
}

/** 取得抽屉容器（承载 ProjectSidebar 的 div）。 */
function drawer(container: HTMLElement): HTMLElement {
  const node = container.querySelector('.app-drawer')
  if (node === null) throw new Error('未找到 .app-drawer 抽屉容器')
  return node as HTMLElement
}

beforeEach(() => {
  useOptimizeStore.getState().reset()
  usePreferenceStore.getState().reset()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('App 响应式抽屉（<768 侧边栏折叠）', () => {
  it('汉堡按钮常驻渲染；初始抽屉关闭（无遮罩、无 --open 类）', () => {
    stubFetch()
    const { container } = render(<App />)

    const burger = screen.getByRole('button', { name: '打开侧边栏' })
    expect(burger.className).toBe('app-titlebar__menu')
    expect(burger.getAttribute('aria-expanded')).toBe('false')
    expect(drawer(container).className).toBe('app-drawer')
    expect(screen.queryByRole('button', { name: '关闭侧边栏' })).toBeNull()
  })

  it('点击汉堡唤出抽屉：加 --open 类并渲染遮罩（侧栏纳入抽屉容器）', async () => {
    const user = userEvent.setup()
    stubFetch()
    const { container } = render(<App />)

    await user.click(screen.getByRole('button', { name: '打开侧边栏' }))

    expect(drawer(container).className).toBe('app-drawer app-drawer--open')
    expect(drawer(container).contains(screen.getByRole('complementary', { name: '项目' }))).toBe(
      true,
    )
    const overlay = screen.getByRole('button', { name: '关闭侧边栏' })
    expect(overlay.className).toBe('app-drawer__overlay')
    expect(screen.getByRole('button', { name: '打开侧边栏' }).getAttribute('aria-expanded')).toBe(
      'true',
    )
  })

  it('点击遮罩关闭抽屉（移除 --open 类与遮罩）', async () => {
    const user = userEvent.setup()
    stubFetch()
    const { container } = render(<App />)

    await user.click(screen.getByRole('button', { name: '打开侧边栏' }))
    await user.click(screen.getByRole('button', { name: '关闭侧边栏' }))

    expect(drawer(container).className).toBe('app-drawer')
    expect(screen.queryByRole('button', { name: '关闭侧边栏' })).toBeNull()
  })

  it('Esc 键关闭抽屉（无障碍）', async () => {
    const user = userEvent.setup()
    stubFetch()
    const { container } = render(<App />)

    await user.click(screen.getByRole('button', { name: '打开侧边栏' }))
    fireEvent.keyDown(document, { key: 'Escape' })

    expect(drawer(container).className).toBe('app-drawer')
    expect(screen.queryByRole('button', { name: '关闭侧边栏' })).toBeNull()
  })
})

describe('App 一键收纳（F-602，2026-10-13）', () => {
  it('点击「收起侧边栏」→ shell 加 --sidebar-collapsed 并关抽屉；点 ☰ 恢复', async () => {
    const user = userEvent.setup()
    stubFetch()
    const { container } = render(<App />)

    const shell = (): HTMLElement => container.querySelector('.app-shell') as HTMLElement
    expect(shell().className).toBe('app-shell')

    await user.click(screen.getByRole('button', { name: '收起侧边栏' }))

    // 桌面端折叠：shell 类切换；侧栏节点仍在（隐藏由 CSS ≥768 规则负责，jsdom 不生效）
    expect(shell().className).toBe('app-shell app-shell--sidebar-collapsed')
    expect(container.querySelector('.project-sidebar')).not.toBeNull()
    expect(drawer(container).className).toBe('app-drawer')

    await user.click(screen.getByRole('button', { name: '打开侧边栏' }))
    expect(shell().className).toBe('app-shell')
  })
})
