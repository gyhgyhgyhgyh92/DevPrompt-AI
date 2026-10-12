import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { AppearancePanel } from './AppearancePanel'

const APPEARANCE_KEY = 'devprompt:v1:appearance'

beforeEach(() => {
  localStorage.clear()
  useSettingsStore.getState().resetAppearance()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  delete document.documentElement.dataset.theme
})

describe('AppearancePanel 通用外观', () => {
  it('主题切换即时设置 data-theme 并持久化 localStorage', () => {
    render(<AppearancePanel />)

    fireEvent.click(screen.getByRole('button', { name: '浅色' }))

    expect(document.documentElement.dataset.theme).toBe('light')
    expect(useSettingsStore.getState().appearance.theme).toBe('light')
    const stored: unknown = JSON.parse(localStorage.getItem(APPEARANCE_KEY) ?? '{}')
    expect(stored).toMatchObject({ theme: 'light' })
  })

  it('跟随系统经 matchMedia 解析为具体主题', () => {
    render(<AppearancePanel />)
    fireEvent.click(screen.getByRole('button', { name: '浅色' }))

    vi.stubGlobal(
      'matchMedia',
      vi.fn().mockReturnValue({
        matches: true,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    )
    fireEvent.click(screen.getByRole('button', { name: '跟随系统' }))
    expect(document.documentElement.dataset.theme).toBe('dark')

    vi.stubGlobal(
      'matchMedia',
      vi.fn().mockReturnValue({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    )
    fireEvent.click(screen.getByRole('button', { name: '深色' }))
    fireEvent.click(screen.getByRole('button', { name: '跟随系统' }))
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('损坏的 localStorage 外观值回退默认（Zod 校验兜底）', async () => {
    vi.resetModules()
    localStorage.setItem(APPEARANCE_KEY, '{not-json')

    const { useSettingsStore: freshStore } = await import('../../stores/useSettingsStore')

    expect(freshStore.getState().appearance).toMatchObject({ theme: 'light', locale: 'zh-CN' })
  })

  it('启动恢复会话开关写入 localStorage 外观项', () => {
    render(<AppearancePanel />)

    fireEvent.click(screen.getByRole('switch', { name: '启动时恢复上次会话' }))

    expect(useSettingsStore.getState().appearance.restoreSessionOnLaunch).toBe(false)
    const stored: unknown = JSON.parse(localStorage.getItem(APPEARANCE_KEY) ?? '{}')
    expect(stored).toMatchObject({ restoreSessionOnLaunch: false })
  })

  it('界面语言的 English 项占位禁用', () => {
    render(<AppearancePanel />)

    const englishOption = screen.getByRole('option', { name: /English/ }) as HTMLOptionElement
    expect(englishOption.disabled).toBe(true)
  })
})
