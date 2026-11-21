import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SettingsResponse } from './api/types'
import { App } from './App'
import { useOptimizeStore } from './stores/useOptimizeStore'
import { useHistoryStore } from './stores/useHistoryStore'
import { useSettingsStore } from './stores/useSettingsStore'

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
  const node = container.querySelector('[data-drawer]')
  if (node === null) throw new Error('未找到 .app-drawer 抽屉容器')
  return node as HTMLElement
}

beforeEach(() => {
  useOptimizeStore.getState().reset()
  useHistoryStore.getState().reset()
  useSettingsStore.setState({ settings: null })
  // 外观是持久化项：每个用例回到默认值，避免上一用例的 theme 泄漏到挂载 effect
  useSettingsStore.getState().resetAppearance()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  delete document.documentElement.dataset.theme
})

describe('App 标题栏 API pill', () => {
  /** 构造一份 /health 载荷：API 项固定 ok，系统项按 need 参数给 ok/坏。 */
  function healthPayload(llmOk: boolean, systemOk: boolean) {
    return {
      code: 0,
      message: 'ok',
      request_id: 'rid',
      data: {
        checks: [
          { name: 'llm_config', ok: llmOk, detail: 'https://api.deepseek.com / deepseek-flash' },
          { name: 'rg', ok: systemOk, detail: 'ripgrep 15.0.0' },
        ],
        is_healthy: llmOk && systemOk,
      },
    }
  }

  function stubHealth(payload: unknown) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(payload)),
    )
  }

  it('API 正常时显示「API 正常」', async () => {
    stubHealth(healthPayload(true, true))
    render(<App />)

    expect(await screen.findByText('API 正常')).toBeTruthy()
  })

  it('llm_config 坏时显示「API 异常」', async () => {
    stubHealth(healthPayload(false, true))
    render(<App />)

    expect(await screen.findByText('API 异常')).toBeTruthy()
  })

  it('无关子系统坏掉**不**误报「API 异常」（回归：曾把用户引向查密钥）', async () => {
    stubHealth(healthPayload(true, false))
    render(<App />)

    expect(await screen.findByText('API 正常')).toBeTruthy()
    expect(screen.queryByText('API 异常')).toBeNull()
  })
})

describe('App 响应式抽屉（<768 侧边栏折叠）', () => {
  it('汉堡按钮常驻渲染；初始抽屉关闭（无遮罩、无 --open 类）', () => {
    stubFetch()
    const { container } = render(<App />)

    const burger = screen.getByRole('button', { name: '打开侧边栏' })
    expect(burger.className).toContain('app-titlebar__menu')
    expect(burger.getAttribute('aria-expanded')).toBe('false')
    expect(drawer(container).className).not.toContain('app-drawer--open')
    expect(screen.queryByRole('button', { name: '关闭侧边栏' })).toBeNull()
  })

  it('点击汉堡唤出抽屉：加 --open 类并渲染遮罩（侧栏纳入抽屉容器）', async () => {
    const user = userEvent.setup()
    stubFetch()
    const { container } = render(<App />)

    await user.click(screen.getByRole('button', { name: '打开侧边栏' }))

    expect(drawer(container).className).toContain('app-drawer--open')
    expect(drawer(container).contains(screen.getByRole('complementary', { name: '项目' }))).toBe(
      true,
    )
    const overlay = screen.getByRole('button', { name: '关闭侧边栏' })
    expect(overlay.className).toContain('app-drawer__overlay')
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

    expect(drawer(container).className).not.toContain('app-drawer--open')
    expect(screen.queryByRole('button', { name: '关闭侧边栏' })).toBeNull()
  })

  it('Esc 键关闭抽屉（无障碍）', async () => {
    const user = userEvent.setup()
    stubFetch()
    const { container } = render(<App />)

    await user.click(screen.getByRole('button', { name: '打开侧边栏' }))
    fireEvent.keyDown(document, { key: 'Escape' })

    expect(drawer(container).className).not.toContain('app-drawer--open')
    expect(screen.queryByRole('button', { name: '关闭侧边栏' })).toBeNull()
  })
})

describe('App 一键收纳（F-602，2026-10-13）', () => {
  it('点击「收起侧边栏」→ shell 加 --sidebar-collapsed 并关抽屉；点 ☰ 恢复', async () => {
    const user = userEvent.setup()
    stubFetch()
    const { container } = render(<App />)

    const shell = (): HTMLElement => container.querySelector('[data-shell]') as HTMLElement
    expect(shell().className).not.toContain('app-shell--sidebar-collapsed')

    await user.click(screen.getByRole('button', { name: '收起侧边栏' }))

    // 桌面端折叠：shell 类切换；侧栏节点仍在（隐藏由 CSS ≥768 规则负责，jsdom 不生效）
    expect(shell().className).toContain('app-shell--sidebar-collapsed')
    expect(container.querySelector('[class*="project-sidebar"]')).not.toBeNull()
    expect(drawer(container).className).not.toContain('app-drawer--open')

    await user.click(screen.getByRole('button', { name: '打开侧边栏' }))
    expect(shell().className).not.toContain('app-shell--sidebar-collapsed')
  })
})

/** 最小设置视图：只保留启动页模型按钮需要的 models 段（其余段按契约兜底）。 */
const settingsFixture: SettingsResponse = {
  models: [
    {
      id: 'm-1',
      provider_id: 'p-1',
      provider: 'DeepSeek',
      model_id: 'deepseek-flash',
      is_active: true,
    },
  ],
  model_service: {
    api_key_masked: 'sk-••••3f7a',
    base_url: 'https://api.deepseek.com',
    model_id: 'deepseek-flash',
    provider: 'DeepSeek',
    timeout: 60,
    max_tokens: null,
    temperature: null,
  },
  process: { followup_cost_budget: 2, followup_soft_round_guard: 12, telemetry: true },
  observability: {
    trace_enabled: true,
    trace_retention_days: 30,
    metrics_enabled: true,
    replay_enabled: true,
  },
  locked: { candidate_limit: 25 },
}

describe('App 主题应用（2026-11-06）', () => {
  const appearance = {
    locale: 'zh-CN',
    codeFont: 'JetBrains Mono',
    restoreSessionOnLaunch: true,
    desktopNotification: false,
  } as const

  it('刷新后按偏好应用暗色（此前只写 index.html 的 light，暗色用户永远看到浅色）', () => {
    stubFetch()
    useSettingsStore.getState().setAppearance({ ...appearance, theme: 'dark' })

    render(<App />)

    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('system 偏好跟随系统深色设置', () => {
    stubFetch()
    vi.stubGlobal('matchMedia', () => ({
      matches: true,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }))
    useSettingsStore.getState().setAppearance({ ...appearance, theme: 'system' })

    render(<App />)

    expect(document.documentElement.dataset.theme).toBe('dark')
  })
})

describe('App 设置预加载（2026-11-03）', () => {
  it('挂载即加载设置：启动页模型按钮显示当前生效模型，不再是「未配置模型」', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) =>
        jsonResponse({
          code: 0,
          message: 'ok',
          request_id: 'rid',
          data: String(input).includes('/api/v1/settings') ? settingsFixture : null,
        }),
      ),
    )

    render(<App />)

    expect(await screen.findByText('deepseek-flash')).toBeTruthy()
    expect(screen.queryByText('未配置模型')).toBeNull()
  })
})

describe('App 桌面形态（Trae 式工作台）', () => {
  afterEach(() => {
    delete window.devpromptDesktop
  })

  it('挂载 preload 桥后进入桌面形态：出现活动栏 / 运行日志面板 / 状态栏', () => {
    window.devpromptDesktop = { pickFolder: vi.fn(async () => ({ path: '' })), platform: 'win32' }
    const { container } = render(<App />)

    expect(container.querySelector('[data-shell]')?.getAttribute('data-shell')).toBe('desktop')
    expect(screen.getByRole('navigation', { name: '桌面导航' })).toBeTruthy()
    expect(screen.getByRole('region', { name: '运行日志' })).toBeTruthy()
    expect(screen.getByRole('contentinfo', { name: '状态栏' })).toBeTruthy()
  })

  it('Web 形态（无桥）：桌面专属区域完全不进 DOM，布局与改造前一致', () => {
    const { container } = render(<App />)

    expect(container.querySelector('[data-shell]')?.getAttribute('data-shell')).toBe('web')
    expect(screen.queryByRole('navigation', { name: '桌面导航' })).toBeNull()
    expect(screen.queryByRole('region', { name: '运行日志' })).toBeNull()
    expect(screen.queryByRole('contentinfo', { name: '状态栏' })).toBeNull()
  })
})
