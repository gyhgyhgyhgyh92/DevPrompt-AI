import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { SettingsResponse } from '../api/types'

const APPEARANCE_KEY = 'devprompt:v1:appearance'

const settingsFixture: SettingsResponse = {
  models: [],
  model_service: {
    api_key_masked: 'sk-••••3f7a',
    base_url: 'https://api.example.com',
    decider: 'auto',
    model_id: 'demo',
    provider: 'DeepSeek',
    timeout: 60,
    max_tokens: null,
    temperature: null,
  },
  process: {
    followup_cost_budget: 1,
    followup_soft_round_guard: 10,
    telemetry: true,
  },
  locked: { candidate_limit: 25 },
}

/** store 在模块初始化时读 localStorage，故每个用例动态重载模块。 */
async function loadStore() {
  vi.resetModules()
  const module = await import('./useSettingsStore')
  return module.useSettingsStore
}

beforeEach(() => {
  localStorage.clear()
})

describe('useSettingsStore localStorage 外观项', () => {
  it('无存储数据时回退默认外观', async () => {
    const store = await loadStore()

    expect(store.getState().appearance).toMatchObject({ theme: 'light', locale: 'zh-CN' })
  })

  it('存储内容损坏（非法 JSON）回退默认值', async () => {
    localStorage.setItem(APPEARANCE_KEY, '{not-json')

    const store = await loadStore()

    expect(store.getState().appearance).toMatchObject({ theme: 'light' })
  })

  it('存储形状不合法（Zod 校验失败）回退默认值', async () => {
    localStorage.setItem(APPEARANCE_KEY, JSON.stringify({ theme: 'neon', locale: 7 }))

    const store = await loadStore()

    expect(store.getState().appearance).toMatchObject({ theme: 'light', locale: 'zh-CN' })
  })

  it('合法数据经 Zod 校验后读出', async () => {
    localStorage.setItem(
      APPEARANCE_KEY,
      JSON.stringify({
        theme: 'light',
        locale: 'en',
        codeFont: 'Fira Code',
        restoreSessionOnLaunch: false,
        desktopNotification: true,
      }),
    )

    const store = await loadStore()

    expect(store.getState().appearance).toMatchObject({ theme: 'light', codeFont: 'Fira Code' })
  })

  it('setAppearance 写入后可被重新读取', async () => {
    const store = await loadStore()
    store.getState().setAppearance({
      theme: 'system',
      locale: 'zh-CN',
      codeFont: 'JetBrains Mono',
      restoreSessionOnLaunch: true,
      desktopNotification: false,
    })

    const reloaded = await loadStore()

    expect(reloaded.getState().appearance).toMatchObject({ theme: 'system' })
  })
})

describe('useSettingsStore 后端设置视图', () => {
  it('setSettings 存入 GET/PUT /settings 数据体', async () => {
    const store = await loadStore()

    store.getState().setSettings(settingsFixture)

    expect(store.getState().settings).toMatchObject({ locked: { candidate_limit: 25 } })
    expect(store.getState().settings?.model_service.api_key_masked).toBe('sk-••••3f7a')
  })
})
