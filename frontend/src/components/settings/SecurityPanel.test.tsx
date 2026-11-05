import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { putSettings } from '../../api/endpoints'
import type { SettingsResponse } from '../../api/types'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { SecurityPanel } from './SecurityPanel'

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
  useSettingsStore.setState({ settings: settingsFixture })
  vi.mocked(putSettings).mockResolvedValue(settingsFixture)
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  delete document.documentElement.dataset.theme
})

describe('SecurityPanel 流程与安全', () => {
  it('候选集上限锁定只读且取值来自 locked.candidate_limit', () => {
    render(<SecurityPanel />)

    const locked = screen.getByLabelText('候选集上限（宪法 MUST-09 锁定）') as HTMLInputElement
    expect(locked.disabled).toBe(true)
    expect(locked.readOnly).toBe(true)
    expect(locked.value).toBe('30')
    expect(screen.getByText(/locked\.candidate_limit/)).toBeTruthy()
  })

  it('护栏参数保存调用 PUT /settings process 段', async () => {
    render(<SecurityPanel />)

    fireEvent.change(screen.getByLabelText('反问软护栏轮数'), { target: { value: '15' } })
    fireEvent.change(screen.getByLabelText('反问成本预算'), { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: '保存流程参数' }))

    await waitFor(() => expect(putSettings).toHaveBeenCalledTimes(1))
    expect(vi.mocked(putSettings).mock.calls[0]?.[0]).toEqual({
      process: { followup_soft_round_guard: 15, followup_cost_budget: 3 },
    })
    await waitFor(() => expect(screen.getByText('已保存')).toBeTruthy())
  })

  it('护栏参数非法时不发请求并提示', async () => {
    render(<SecurityPanel />)

    fireEvent.change(screen.getByLabelText('反问软护栏轮数'), { target: { value: 'abc' } })
    fireEvent.click(screen.getByRole('button', { name: '保存流程参数' }))

    await waitFor(() => expect(screen.getByText('护栏参数必须是数字')).toBeTruthy())
    expect(putSettings).not.toHaveBeenCalled()
  })

  it('遥测开关触发 PUT /settings telemetry', async () => {
    render(<SecurityPanel />)

    fireEvent.click(screen.getByRole('switch', { name: '遥测' }))

    await waitFor(() => expect(putSettings).toHaveBeenCalledTimes(1))
    expect(vi.mocked(putSettings).mock.calls[0]?.[0]).toEqual({ process: { telemetry: false } })
  })

  it('清除本地数据需二次确认并清空全部 devprompt:v1: 键', async () => {
    localStorage.setItem('devprompt:v1:sessions', '[]')
    localStorage.setItem('devprompt:v1:appearance', '{"theme":"dark"}')
    render(<SecurityPanel />)

    fireEvent.click(screen.getByRole('button', { name: '清除本地数据' }))
    expect(screen.getByRole('button', { name: '确认清除？' })).toBeTruthy()
    expect(localStorage.getItem('devprompt:v1:sessions')).toBe('[]')

    fireEvent.click(screen.getByRole('button', { name: '确认清除？' }))

    await waitFor(() => expect(localStorage.getItem('devprompt:v1:sessions')).toBeNull())
    expect(localStorage.getItem('devprompt:v1:appearance')).toBeNull()
    expect(screen.getByText('已清除本地数据')).toBeTruthy()
  })
})
