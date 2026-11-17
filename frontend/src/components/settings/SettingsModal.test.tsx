import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router'
import { getHistory, getSettings, putSettings } from '../../api/endpoints'
import type { SettingsResponse } from '../../api/types'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { SettingsModal } from './SettingsModal'

vi.mock('../../api/endpoints', () => ({
  getSettings: vi.fn(),
  putSettings: vi.fn(),
  getHealth: vi.fn(),
  getHistory: vi.fn(),
  getSessionEvents: vi.fn(async () => []),
  openSessionStream: vi.fn(() => () => undefined),
}))

const settingsFixture: SettingsResponse = {
  models: [],
  model_service: {
    api_key_masked: 'sk-••••3f7a',
    base_url: 'https://api.example.com',
    model_id: 'demo-model',
    provider: 'DeepSeek',
    timeout: 60,
    max_tokens: null,
    temperature: null,
  },
  process: {
    followup_cost_budget: 2,
    followup_soft_round_guard: 12,
    telemetry: true,
  },
  observability: {
    trace_enabled: true,
    trace_retention_days: 30,
    metrics_enabled: true,
    replay_enabled: true,
  },
  locked: { candidate_limit: 30 },
}

/** 弹窗需要 Router 上下文（可观测性项跳转独立页面）。 */
function renderModal(props: { open?: boolean; onClose?: () => void } = {}) {
  const onClose = props.onClose ?? vi.fn()
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<SettingsModal open={props.open ?? true} onClose={onClose} />} />
        <Route path="/observability" element={<div>可观测性独立页面</div>} />
      </Routes>
    </MemoryRouter>,
  )
  return onClose
}

beforeEach(() => {
  localStorage.clear()
  useSettingsStore.setState({ settings: null })
  vi.mocked(getSettings).mockResolvedValue(settingsFixture)
  vi.mocked(getHistory).mockResolvedValue({
    items: [],
    has_more: false,
    limit: 50,
    offset: 0,
  })
  vi.mocked(putSettings).mockResolvedValue(settingsFixture)
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('SettingsModal 契约与开关行为', () => {
  it('open=false 渲染 null', () => {
    renderModal({ open: false })

    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('open=true 渲染四项导航且焦点移入面板', async () => {
    renderModal()

    expect(screen.getByRole('dialog', { name: '设置' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '模型服务' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '通用外观' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '可观测性' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '流程与安全' })).toBeTruthy()
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole('dialog', { name: '设置' })),
    )
  })

  it('点击可观测性关闭弹窗并跳转独立页面', async () => {
    const user = userEvent.setup()
    const onClose = renderModal()

    await user.click(screen.getByRole('button', { name: '可观测性' }))

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('可观测性独立页面')).toBeTruthy()
    // 弹窗内不再渲染可观测性内容（内容唯一一份，在独立页面）
    expect(screen.queryByRole('dialog', { name: '设置' })).toBeNull()
    expect(screen.queryByRole('tablist', { name: '可观测性' })).toBeNull()
  })

  it('Esc 触发 onClose', async () => {
    const user = userEvent.setup()
    const onClose = renderModal()

    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('关闭按钮触发 onClose', () => {
    const onClose = renderModal()

    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('关闭后焦点归还触发按钮', async () => {
    const user = userEvent.setup()
    function Wrap() {
      const [open, setOpen] = useState(false)
      return (
        <MemoryRouter>
          <div>
            <button type="button" onClick={() => setOpen(true)}>
              打开设置
            </button>
            <SettingsModal open={open} onClose={() => setOpen(false)} />
          </div>
        </MemoryRouter>
      )
    }
    render(<Wrap />)

    const trigger = screen.getByRole('button', { name: '打开设置' })
    await user.click(trigger)
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole('dialog', { name: '设置' })),
    )

    await user.keyboard('{Escape}')
    await waitFor(() => expect(document.activeElement).toBe(trigger))
  })

  it('三项导航切换渲染对应面板', async () => {
    renderModal()
    await waitFor(() => expect(useSettingsStore.getState().settings).not.toBeNull())

    fireEvent.click(screen.getByRole('button', { name: '通用外观' }))
    expect(screen.getByRole('heading', { name: '通用外观' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '流程与安全' }))
    expect(screen.getByRole('heading', { name: '流程与安全' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '模型服务' }))
    expect(screen.getByRole('heading', { name: '模型服务' })).toBeTruthy()
  })

  it('打开时 GET /settings 回填 store', async () => {
    renderModal()

    await waitFor(() => expect(getSettings).toHaveBeenCalledTimes(1))
    expect(useSettingsStore.getState().settings).toEqual(settingsFixture)
  })
})
