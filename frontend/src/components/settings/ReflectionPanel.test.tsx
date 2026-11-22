import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getHealth, putSettings } from '../../api/endpoints'
import type { SettingsResponse } from '../../api/types'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { ReflectionPanel } from './ReflectionPanel'

vi.mock('../../api/endpoints', () => ({
  getSettings: vi.fn(),
  putSettings: vi.fn(),
  getHealth: vi.fn(),
}))

function settingsFixture(enabled = false): SettingsResponse {
  return {
    models: [],
    model_service: {
      api_key_masked: '',
      base_url: 'https://api.example.com',
      model_id: 'demo-model',
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
    reflection: { enabled, base_url: 'http://127.0.0.1:3111', top_k: 5 },
    locked: { candidate_limit: 30 },
  }
}

/** /health 的 reflection 检查项：detail 用后端稳定标记 disabled 表示「未启用」。 */
function healthWith(name: 'reflection', ok: boolean, detail: string) {
  return { checks: [{ name, ok, detail }], is_healthy: ok }
}

beforeEach(() => {
  localStorage.clear()
  useSettingsStore.setState({ settings: settingsFixture() })
  vi.mocked(putSettings).mockResolvedValue(settingsFixture(true))
  vi.mocked(getHealth).mockResolvedValue(healthWith('reflection', true, 'disabled'))
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('ReflectionPanel 自进化', () => {
  it('未启用时徽标显示未启用，且开关为关', async () => {
    render(<ReflectionPanel />)

    expect(screen.getByRole('heading', { name: '自进化（Reflection）' })).toBeTruthy()
    const toggle = screen.getByRole('switch', { name: '启用自进化' })
    expect(toggle.getAttribute('aria-checked')).toBe('false')
    await waitFor(() => expect(screen.getByText('未启用')).toBeTruthy())
  })

  it('打开开关即保存，只提交 enabled 段', async () => {
    const user = userEvent.setup()
    render(<ReflectionPanel />)
    await waitFor(() => expect(getHealth).toHaveBeenCalled())

    await user.click(screen.getByRole('switch', { name: '启用自进化' }))

    expect(putSettings).toHaveBeenCalledWith({ reflection: { enabled: true } })
    await waitFor(() => expect(screen.getByText('已保存')).toBeTruthy())
  })

  it('侧车可用时徽标显示已连接', async () => {
    vi.mocked(getHealth).mockResolvedValue(healthWith('reflection', true, 'http://127.0.0.1:3111'))
    useSettingsStore.setState({ settings: settingsFixture(true) })

    render(<ReflectionPanel />)

    await waitFor(() => expect(screen.getByText('已连接')).toBeTruthy())
  })

  it('侧车不可达时徽标显示未连接并附原因', async () => {
    vi.mocked(getHealth).mockResolvedValue(healthWith('reflection', false, 'secret_missing'))
    useSettingsStore.setState({ settings: settingsFixture(true) })

    render(<ReflectionPanel />)

    await waitFor(() => expect(screen.getByText('未连接（secret_missing）')).toBeTruthy())
  })

  it('保存连接设置时提交地址与召回条数', async () => {
    const user = userEvent.setup()
    render(<ReflectionPanel />)
    await waitFor(() => expect(getHealth).toHaveBeenCalled())

    const baseUrl = screen.getByLabelText('经验库地址（agentmemory 侧车）')
    const topK = screen.getByLabelText('单轮召回条数')
    await user.clear(baseUrl)
    await user.type(baseUrl, 'http://127.0.0.1:4000')
    await user.clear(topK)
    await user.type(topK, '8')
    await user.click(screen.getByRole('button', { name: '保存连接设置' }))

    expect(putSettings).toHaveBeenCalledWith({
      reflection: { base_url: 'http://127.0.0.1:4000', top_k: 8 },
    })
  })

  it('召回条数越界时本地拦截，不发请求', async () => {
    render(<ReflectionPanel />)
    await waitFor(() => expect(getHealth).toHaveBeenCalled())

    fireEvent.change(screen.getByLabelText('单轮召回条数'), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: '保存连接设置' }))

    expect(putSettings).not.toHaveBeenCalled()
    expect(screen.getByText('召回条数需在 1–20 之间')).toBeTruthy()
  })

  it('召回条数超过上限时同样本地拦截（与后端 le=20 对齐）', async () => {
    render(<ReflectionPanel />)
    await waitFor(() => expect(getHealth).toHaveBeenCalled())

    fireEvent.change(screen.getByLabelText('单轮召回条数'), { target: { value: '21' } })
    fireEvent.click(screen.getByRole('button', { name: '保存连接设置' }))

    expect(putSettings).not.toHaveBeenCalled()
    expect(screen.getByText('召回条数需在 1–20 之间')).toBeTruthy()
  })
})
