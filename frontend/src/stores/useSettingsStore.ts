import type { z } from 'zod'
import { create } from 'zustand'
import type { SettingsResponse } from '../api/types'
import type { AppearanceSettings } from '../schemas/settings'
import { AppearanceSettingsSchema } from '../schemas/settings'

/** 版本化键前缀：结构变更时可安全失效（真源 §12 约定 devprompt:v1:）。 */
export const STORAGE_PREFIX = 'devprompt:v1:'
export const APPEARANCE_KEY = `${STORAGE_PREFIX}appearance`

const defaultAppearance: AppearanceSettings = {
  theme: 'light',
  locale: 'zh-CN',
  codeFont: 'JetBrains Mono',
  restoreSessionOnLaunch: true,
  desktopNotification: false,
}

/** localStorage 读写封装：内容可能被用户手动改坏，读取一律过 Zod 校验后兜底。 */
function readSetting<T>(key: string, fallback: T, schema: z.ZodType<T>): T {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return fallback
    const parsed: unknown = JSON.parse(raw)
    const result = schema.safeParse(parsed)
    return result.success ? result.data : fallback
  } catch {
    return fallback
  }
}

function writeSetting(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // 配额满或隐私模式：静默失败，设置仅本次会话生效
  }
}

/** 跟随系统主题经 matchMedia 解析为具体主题（jsdom 无 matchMedia 时按浅色兜底，与默认基调一致）。 */
function resolveTheme(theme: AppearanceSettings['theme']): 'light' | 'dark' {
  if (theme !== 'system') return theme
  const prefersDark =
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
  return prefersDark ? 'dark' : 'light'
}

/**
 * 主题即时生效（F-604）：写根节点 data-theme，tokens.css 据此切换；
 * 「跟随系统」在应用时解析，不写回持久化值。
 */
export function applyAppearanceTheme(theme: AppearanceSettings['theme']): void {
  document.documentElement.dataset.theme = resolveTheme(theme)
}

/** 清除全部本地留存（SecurityPanel）：只删 devprompt:v1: 前缀键，不触碰其他来源数据。 */
function removeLocalData(): void {
  for (const key of Object.keys(localStorage)) {
    if (key.startsWith(STORAGE_PREFIX)) {
      localStorage.removeItem(key)
    }
  }
}

/**
 * 设置状态（F-604）：模型服务/流程参数走后端 GET/PUT /settings（store 只存结果），
 * 通用外观项进 localStorage（devprompt:v1: 前缀 + Zod 读取校验）。
 */
interface SettingsState {
  /** 后端设置视图（GET/PUT /settings 数据体）。 */
  settings: SettingsResponse | null
  appearance: AppearanceSettings
  setSettings: (settings: SettingsResponse) => void
  setAppearance: (appearance: AppearanceSettings) => void
  resetAppearance: () => void
  clearLocalData: () => void
}

export const useSettingsStore = create<SettingsState>()((set) => ({
  settings: null,
  appearance: readSetting(APPEARANCE_KEY, defaultAppearance, AppearanceSettingsSchema),
  setSettings: (settings) => set({ settings }),
  setAppearance: (appearance) => {
    writeSetting(APPEARANCE_KEY, appearance)
    set({ appearance })
  },
  resetAppearance: () => {
    writeSetting(APPEARANCE_KEY, defaultAppearance)
    set({ appearance: defaultAppearance })
  },
  clearLocalData: () => {
    removeLocalData()
    set({ appearance: defaultAppearance })
  },
}))
