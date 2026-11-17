import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  getHistory,
  getObsEvents,
  getObsTraces,
  getSessionEvents,
  putSettings,
} from '../../api/endpoints'
import type { SettingsResponse } from '../../api/types'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { ObservabilityPanel } from './ObservabilityPanel'

vi.mock('../../api/endpoints', () => ({
  getHistory: vi.fn(),
  getSessionEvents: vi.fn(async () => []),
  openSessionStream: vi.fn(() => () => undefined),
  getObsTraces: vi.fn(),
  getObsEvents: vi.fn(),
  getObsEvent: vi.fn(),
  getObsMetricsSummary: vi.fn(async () => ({ items: [], schema_version: 1 })),
  getObsAlerts: vi.fn(async () => ({ items: [], limit: 50, offset: 0, schema_version: 1 })),
  getObsMetricsConfig: vi.fn(async () => ({ config: {}, schema_version: 1 })),
  getObsReplayRun: vi.fn(),
  putSettings: vi.fn(),
}))

function settingsFixture(overrides: Partial<SettingsResponse['observability']> = {}) {
  return {
    models: [],
    model_service: {
      api_key_masked: '',
      base_url: '',
      model_id: '',
      provider: '',
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
      ...overrides,
    },
    locked: { candidate_limit: 30 },
  } satisfies SettingsResponse
}

beforeEach(() => {
  useSettingsStore.setState({ settings: settingsFixture() })
  vi.mocked(getHistory).mockResolvedValue({
    items: [
      {
        session_id: 's-1',
        state: 'DONE',
        project: 'demo',
        project_root: 'C:/demo',
        updated_at: '2026-11-12T00:00:00Z',
        title: '可观测性会话',
        pinned: false,
      },
    ],
    has_more: false,
    limit: 50,
    offset: 0,
  })
  vi.mocked(getObsTraces).mockResolvedValue({ items: [], schema_version: 1 })
  vi.mocked(getObsEvents).mockResolvedValue({
    items: [],
    has_more: false,
    next_cursor: 0,
    schema_version: 1,
  })
  vi.mocked(putSettings).mockResolvedValue(settingsFixture())
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  useSettingsStore.setState({ settings: null })
})

describe('ObservabilityPanel', () => {
  it('默认选中 Session Log 并拉取运行时事件', async () => {
    render(<ObservabilityPanel />)

    expect(screen.getByText('可观测性')).toBeTruthy()
    expect(screen.getByRole('tab', { name: 'Session Log' })).toBeTruthy()
    await waitFor(() => expect(getSessionEvents).toHaveBeenCalledWith('s-1', 1 << 30, 200))
  })

  it('关闭模块后隐藏对应标签并保存到后端', async () => {
    const user = userEvent.setup()
    render(<ObservabilityPanel />)

    await user.click(screen.getByRole('checkbox', { name: 'Metrics 指标' }))
    expect(screen.queryByRole('tab', { name: 'Metrics' })).toBeNull()

    vi.mocked(putSettings).mockResolvedValue(settingsFixture({ metrics_enabled: false }))
    await user.click(screen.getByRole('button', { name: '保存' }))

    expect(putSettings).toHaveBeenCalledWith({
      observability: {
        trace_enabled: true,
        trace_retention_days: 30,
        metrics_enabled: false,
        replay_enabled: true,
      },
    })
    await waitFor(() => expect(screen.getByText('已保存，立即生效')).toBeTruthy())
  })

  it('三个模块全部关闭后 Session Log 仍可用', async () => {
    const user = userEvent.setup()
    render(<ObservabilityPanel />)

    await user.click(screen.getByRole('checkbox', { name: 'Trace 采集' }))
    await user.click(screen.getByRole('checkbox', { name: 'Metrics 指标' }))
    await user.click(screen.getByRole('checkbox', { name: 'Replay 回放' }))

    expect(screen.getAllByRole('tab')).toHaveLength(1)
    expect(screen.getByRole('tab', { name: 'Session Log' })).toBeTruthy()
    expect(screen.getByText(/events:/)).toBeTruthy()
  })

  it('四个模块标签悬停显示中文气泡，移出自动隐藏', async () => {
    const user = userEvent.setup()
    render(<ObservabilityPanel />)

    const cases: Array<[string, string, string]> = [
      ['Session Log', 'obs-module-tip-session-log', '运行事件台账'],
      ['Trace', 'obs-module-tip-trace', '调用链追踪'],
      ['Metrics', 'obs-module-tip-metrics', '指标与告警'],
      ['Replay', 'obs-module-tip-replay', '确定性回放'],
    ]

    for (const [label, tipId, title] of cases) {
      const tab = screen.getByRole('tab', { name: label })
      expect(tab.getAttribute('aria-describedby')).toBe(tipId)
      const tip = document.getElementById(tipId) as HTMLElement
      expect(tip.getAttribute('role')).toBe('tooltip')
      expect(tip.getAttribute('data-open')).toBe('false')

      await user.hover(tab)
      expect(tip.getAttribute('data-open')).toBe('true')
      expect(tip.textContent).toContain(title)
      expect(tip.textContent).toContain('定义')
      expect(tip.textContent).toContain('核心功能')
      expect(tip.textContent).toContain('使用场景')

      await user.unhover(tab)
      expect(tip.getAttribute('data-open')).toBe('false')
    }
  })
})
