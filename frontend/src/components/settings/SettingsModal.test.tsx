import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getHistory, getSettings, putSettings } from '../../api/endpoints'
import type { SettingsResponse } from '../../api/types'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { SettingsModal } from './SettingsModal'

vi.mock('../../api/endpoints', () => ({
  getSettings: vi.fn(),
  putSettings: vi.fn(),
  getHealth: vi.fn(),
  getHistory: vi.fn(),
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
  locked: { candidate_limit: 30 },
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
    render(<SettingsModal open={false} onClose={vi.fn()} />)

    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('open=true 渲染三项导航且焦点移入面板', async () => {
    render(<SettingsModal open onClose={vi.fn()} />)

    expect(screen.getByRole('dialog', { name: '设置' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '⚙ 模型服务' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '◐ 通用外观' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '⚑ 流程与安全' })).toBeTruthy()
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole('dialog', { name: '设置' })),
    )
  })

  it('Esc 触发 onClose', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<SettingsModal open onClose={onClose} />)

    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('✕ 按钮触发 onClose', () => {
    const onClose = vi.fn()
    render(<SettingsModal open onClose={onClose} />)

    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('关闭后焦点归还触发按钮', async () => {
    const user = userEvent.setup()
    function Wrap() {
      const [open, setOpen] = useState(false)
      return (
        <div>
          <button type="button" onClick={() => setOpen(true)}>
            打开设置
          </button>
          <SettingsModal open={open} onClose={() => setOpen(false)} />
        </div>
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
    render(<SettingsModal open onClose={vi.fn()} />)
    await waitFor(() => expect(useSettingsStore.getState().settings).not.toBeNull())

    fireEvent.click(screen.getByRole('button', { name: '◐ 通用外观' }))
    expect(screen.getByRole('heading', { name: '通用外观' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '⚑ 流程与安全' }))
    expect(screen.getByRole('heading', { name: '流程与安全' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '⚙ 模型服务' }))
    expect(screen.getByRole('heading', { name: '模型服务' })).toBeTruthy()
  })

  it('打开时 GET /settings 回填 store', async () => {
    render(<SettingsModal open onClose={vi.fn()} />)

    await waitFor(() => expect(getSettings).toHaveBeenCalledTimes(1))
    expect(useSettingsStore.getState().settings).toEqual(settingsFixture)
  })
})
