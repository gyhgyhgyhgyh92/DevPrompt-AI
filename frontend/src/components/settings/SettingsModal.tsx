import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getSettings } from '../../api/endpoints'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { AppearancePanel } from './AppearancePanel'
import { errorMessage } from './errorMessage'
import { ModelServicePanel } from './ModelServicePanel'
import { ObservabilityPanel } from './ObservabilityPanel'
import { SecurityPanel } from './SecurityPanel'
import styles from './settings.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

export interface SettingsModalProps {
  open: boolean
  onClose: () => void
}

type TabKey = 'model-service' | 'appearance' | 'observability' | 'security'

const TAB_KEYS = ['model-service', 'appearance', 'observability', 'security'] as const
const TAB_ICONS: Record<(typeof TAB_KEYS)[number], string> = {
  'model-service': '⚙',
  appearance: '◐',
  observability: '◎',
  security: '⚑',
}

/**
 * 设置中心模态（F-604）：左侧四项导航 + 右侧内容区；
 * Esc/✕ 关闭，打开时焦点入面板、关闭归还触发按钮（无障碍惯例，非状态逻辑）。
 */
export function SettingsModal(props: SettingsModalProps) {
  const { t } = useTranslation()
  const setSettings = useSettingsStore((state) => state.setSettings)
  const [activeTab, setActiveTab] = useState<TabKey>('model-service')
  const [loadError, setLoadError] = useState('')
  const panelRef = useRef<HTMLDivElement | null>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  // 焦点管理：打开时记住触发元素并把焦点移入面板；关闭（卸载内容）时归还
  useEffect(() => {
    if (!props.open) return
    previousFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    panelRef.current?.focus()
    return () => {
      previousFocusRef.current?.focus()
      previousFocusRef.current = null
    }
  }, [props.open])

  useEffect(() => {
    if (!props.open) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') props.onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [props.open, props.onClose])

  // 打开时回读后端设置（store 只存结果，fetch 在容器组件，MUST-16）
  useEffect(() => {
    if (!props.open) return
    let cancelled = false
    setLoadError('')
    getSettings()
      .then((next) => {
        if (!cancelled) setSettings(next)
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadError(errorMessage(error, t('settings.load_failed')))
      })
    return () => {
      cancelled = true
    }
  }, [props.open, setSettings])

  if (!props.open) return null

  return (
    <div className={s('settings-overlay')}>
      <div
        className={s('settings-modal')}
        data-tab={activeTab}
        role="dialog"
        aria-modal="true"
        aria-label={t('settings.modal.title')}
        ref={panelRef}
        tabIndex={-1}
      >
        <header className={s('settings-modal__header')}>
          <h2 className={s('settings-modal__title')}>{t('settings.modal.title')}</h2>
          <button
            type="button"
            className={s('settings-close')}
            aria-label={t('common.close')}
            onClick={props.onClose}
          >
            ✕
          </button>
        </header>
        <div className={s('settings-modal__body')}>
          <nav className={s('settings-nav')} aria-label={t('settings.nav.label')}>
            {TAB_KEYS.map((key) => (
              <button
                key={key}
                type="button"
                aria-current={activeTab === key ? 'page' : undefined}
                className={s(
                  activeTab === key
                    ? 'settings-nav__item settings-nav__item--active'
                    : 'settings-nav__item',
                )}
                onClick={() => setActiveTab(key)}
              >
                {TAB_ICONS[key]} {t(`settings.tab.${key}`)}
              </button>
            ))}
          </nav>
          <div className={s('settings-content')}>
            {loadError !== '' ? (
              <p className={s('settings-status settings-status--error')}>{loadError}</p>
            ) : null}
            {activeTab === 'model-service' ? <ModelServicePanel /> : null}
            {activeTab === 'appearance' ? <AppearancePanel /> : null}
            {activeTab === 'observability' ? <ObservabilityPanel /> : null}
            {activeTab === 'security' ? <SecurityPanel /> : null}
          </div>
        </div>
      </div>
    </div>
  )
}
