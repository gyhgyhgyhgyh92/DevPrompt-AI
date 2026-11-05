import { useEffect } from 'react'
import type { AppearanceSettings } from '../../schemas/settings'
import { applyAppearanceTheme, useSettingsStore } from '../../stores/useSettingsStore'
import { Toggle } from '../ui/Toggle'
import './settings.css'

type Theme = AppearanceSettings['theme']

const THEME_OPTIONS: ReadonlyArray<{ value: Theme; label: string }> = [
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
  { value: 'system', label: '跟随系统' },
]

const CODE_FONTS: readonly string[] = ['JetBrains Mono', 'Cascadia Code', 'Consolas', 'Courier New']

/** 主题缩略预览：直接挂 data-theme 让 tokens.css 自行解析配色，前端不复制颜色值。 */
function ThemePreview(props: { theme: Theme }) {
  if (props.theme === 'system') {
    return (
      <span className="theme-preview" aria-hidden="true">
        <span className="theme-preview" data-theme="light">
          <span className="theme-preview__bar" />
        </span>
        <span className="theme-preview" data-theme="dark">
          <span className="theme-preview__chip" />
        </span>
      </span>
    )
  }
  return (
    <span className="theme-preview" data-theme={props.theme} aria-hidden="true">
      <span className="theme-preview__bar" />
      <span className="theme-preview__chip" />
    </span>
  )
}

/** 通用外观面板（F-604 外观标签页）：主题/语言/字体/开关，全部持久化在 localStorage。 */
export function AppearancePanel() {
  const appearance = useSettingsStore((state) => state.appearance)
  const setAppearance = useSettingsStore((state) => state.setAppearance)

  useEffect(() => {
    applyAppearanceTheme(appearance.theme)
  }, [appearance.theme])

  const update = (patch: Partial<AppearanceSettings>) => {
    const next = { ...appearance, ...patch }
    setAppearance(next)
    if (patch.theme !== undefined) applyAppearanceTheme(next.theme)
  }

  const codeFontOptions = CODE_FONTS.includes(appearance.codeFont)
    ? CODE_FONTS
    : [...CODE_FONTS, appearance.codeFont]

  return (
    <section className="settings-panel" aria-label="通用外观">
      <h3 className="settings-panel__title">通用外观</h3>
      <div className="settings-field">
        <span className="settings-label">主题</span>
        <div className="settings-segment" role="group" aria-label="主题">
          {THEME_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={appearance.theme === option.value}
              className={
                appearance.theme === option.value
                  ? 'settings-segment__item settings-segment__item--active'
                  : 'settings-segment__item'
              }
              onClick={() => update({ theme: option.value })}
            >
              <ThemePreview theme={option.value} />
              {option.label}
            </button>
          ))}
        </div>
      </div>
      <div className="settings-field">
        <label className="settings-label" htmlFor="settings-locale">
          界面语言
        </label>
        <select
          id="settings-locale"
          className="settings-select"
          value={appearance.locale}
          onChange={(event) =>
            update({ locale: event.currentTarget.value as AppearanceSettings['locale'] })
          }
        >
          <option value="zh-CN">简体中文</option>
          <option value="en">English</option>
        </select>
        <span className="settings-hint">切换后界面文案即时生效</span>
      </div>
      <div className="settings-field">
        <label className="settings-label" htmlFor="settings-code-font">
          代码字体
        </label>
        <select
          id="settings-code-font"
          className="settings-select"
          value={appearance.codeFont}
          onChange={(event) => update({ codeFont: event.currentTarget.value })}
        >
          {codeFontOptions.map((font) => (
            <option key={font} value={font}>
              {font}
            </option>
          ))}
        </select>
      </div>
      <div className="settings-row">
        <span className="settings-label">启动时恢复上次会话</span>
        <Toggle
          label="启动时恢复上次会话"
          checked={appearance.restoreSessionOnLaunch}
          onChange={(checked) => update({ restoreSessionOnLaunch: checked })}
        />
      </div>
      <div className="settings-row">
        <span className="settings-label">桌面通知</span>
        <Toggle
          label="桌面通知"
          checked={appearance.desktopNotification}
          onChange={(checked) => update({ desktopNotification: checked })}
        />
      </div>
    </section>
  )
}
