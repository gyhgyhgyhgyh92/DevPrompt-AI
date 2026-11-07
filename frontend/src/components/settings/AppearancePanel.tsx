import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import type { AppearanceSettings } from '../../schemas/settings'
import { applyAppearanceTheme, useSettingsStore } from '../../stores/useSettingsStore'
import { Toggle } from '../ui/Toggle'
import styles from './settings.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

type Theme = AppearanceSettings['theme']

const THEME_VALUES: readonly Theme[] = ['light', 'dark', 'system']
const THEME_TEXT_KEY: Record<Theme, string> = {
  light: 'settings.appearance.theme_light',
  dark: 'settings.appearance.theme_dark',
  system: 'settings.appearance.theme_system',
}

const CODE_FONTS: readonly string[] = ['JetBrains Mono', 'Cascadia Code', 'Consolas', 'Courier New']

/** 主题缩略预览：直接挂 data-theme 让 tokens.css 自行解析配色，前端不复制颜色值。 */
function ThemePreview(props: { theme: Theme }) {
  if (props.theme === 'system') {
    return (
      <span className={s('theme-preview')} aria-hidden="true">
        <span className={s('theme-preview')} data-theme="light">
          <span className={s('theme-preview__bar')} />
        </span>
        <span className={s('theme-preview')} data-theme="dark">
          <span className={s('theme-preview__chip')} />
        </span>
      </span>
    )
  }
  return (
    <span className={s('theme-preview')} data-theme={props.theme} aria-hidden="true">
      <span className={s('theme-preview__bar')} />
      <span className={s('theme-preview__chip')} />
    </span>
  )
}

/** 通用外观面板（F-604 外观标签页）：主题/语言/字体/开关，全部持久化在 localStorage。 */
export function AppearancePanel() {
  const { t } = useTranslation()
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
    <section className={s('settings-panel')} aria-label={t('settings.appearance.title')}>
      <h3 className={s('settings-panel__title')}>{t('settings.appearance.title')}</h3>
      <div className={s('settings-field')}>
        <span className={s('settings-label')}>{t('settings.appearance.theme')}</span>
        <div
          className={s('settings-segment')}
          role="group"
          aria-label={t('settings.appearance.theme')}
        >
          {THEME_VALUES.map((theme) => (
            <button
              key={theme}
              type="button"
              aria-pressed={appearance.theme === theme}
              className={s(
                appearance.theme === theme
                  ? 'settings-segment__item settings-segment__item--active'
                  : 'settings-segment__item',
              )}
              onClick={() => update({ theme })}
            >
              <ThemePreview theme={theme} />
              {t(THEME_TEXT_KEY[theme])}
            </button>
          ))}
        </div>
      </div>
      <div className={s('settings-field')}>
        <label className={s('settings-label')} htmlFor="settings-locale">
          {t('settings.appearance.locale')}
        </label>
        <select
          id="settings-locale"
          className={s('settings-select')}
          value={appearance.locale}
          onChange={(event) =>
            update({ locale: event.currentTarget.value as AppearanceSettings['locale'] })
          }
        >
          <option value="zh-CN">简体中文</option>
          <option value="en">English</option>
        </select>
        <span className={s('settings-hint')}>{t('settings.appearance.locale_hint')}</span>
      </div>
      <div className={s('settings-field')}>
        <label className={s('settings-label')} htmlFor="settings-code-font">
          {t('settings.appearance.code_font')}
        </label>
        <select
          id="settings-code-font"
          className={s('settings-select')}
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
      <div className={s('settings-row')}>
        <span className={s('settings-label')}>{t('settings.appearance.restore_session')}</span>
        <Toggle
          label={t('settings.appearance.restore_session')}
          checked={appearance.restoreSessionOnLaunch}
          onChange={(checked) => update({ restoreSessionOnLaunch: checked })}
        />
      </div>
      <div className={s('settings-row')}>
        <span className={s('settings-label')}>{t('settings.appearance.desktop_notification')}</span>
        <Toggle
          label={t('settings.appearance.desktop_notification')}
          checked={appearance.desktopNotification}
          onChange={(checked) => update({ desktopNotification: checked })}
        />
      </div>
    </section>
  )
}
