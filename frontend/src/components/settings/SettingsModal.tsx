import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { getSettings } from '../../api/endpoints'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { AppearancePanel } from './AppearancePanel'
import { errorMessage } from './errorMessage'
import { ExtensionsPanel } from './ExtensionsPanel'
import { ModelServicePanel } from './ModelServicePanel'
import { SecurityPanel } from './SecurityPanel'
import styles from './settings.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

export interface SettingsModalProps {
  open: boolean
  onClose: () => void
}

/** 弹窗内可切换的面板；左侧导航第四项是可观测性入口（跳转独立页面），不属此列。 */
type PanelKey = 'model-service' | 'appearance' | 'security' | 'extensions'
type NavKey = PanelKey | 'observability'

/** 可观测性独立页面路由（内容唯一一份，弹窗内不再展开，MUST-10）。 */
const OBSERVABILITY_ROUTE = '/observability'

const NAV_KEYS: NavKey[] = [
  'model-service',
  'appearance',
  'observability',
  'security',
  'extensions',
]
const TAB_ICONS: Record<NavKey, string> = {
  'model-service': '⚙',
  appearance: '◐',
  observability: '◎',
  security: '⚑',
  extensions: '⌘',
}

/**
 * 设置中心模态（F-604）：左侧四项导航 + 右侧内容区；
 * Esc/✕ 关闭，打开时焦点入面板、关闭归还触发按钮（无障碍惯例，非状态逻辑）。
 *
 * 2026-11-16：可观测性项位置不变，但点击改为关闭弹窗并跳转独立页面 /observability，
 * 弹窗内不再渲染可观测性内容（避免同一功能出现两份实现）。
 */
export function SettingsModal(props: SettingsModalProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const setSettings = useSettingsStore((state) => state.setSettings)
  const [activeTab, setActiveTab] = useState<PanelKey>('model-service')
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

  /** 导航项行为：可观测性项跳转独立页面，其余三项切换面板。 */
  function handleNav(key: NavKey): void {
    if (key === 'observability') {
      props.onClose()
      navigate(OBSERVABILITY_ROUTE)
      return
    }
    setActiveTab(key)
  }

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
            {NAV_KEYS.map((key) => (
              <button
                key={key}
                type="button"
                aria-current={key !== 'observability' && activeTab === key ? 'page' : undefined}
                className={s(
                  key !== 'observability' && activeTab === key
                    ? 'settings-nav__item settings-nav__item--active'
                    : 'settings-nav__item',
                )}
                onClick={() => handleNav(key)}
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
            {activeTab === 'security' ? <SecurityPanel /> : null}
            {activeTab === 'extensions' ? <ExtensionsPanel /> : null}
          </div>
        </div>
      </div>
    </div>
  )
}
