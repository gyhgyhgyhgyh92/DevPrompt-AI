import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { Activity, Info, Palette, Plug, Settings, ShieldCheck, Sparkles, X } from 'lucide-react'
import { getSettings } from '../../api/endpoints'
import { useFocusTrap } from '../../hooks/useFocusTrap'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { AboutPanel } from './AboutPanel'
import { AppearancePanel } from './AppearancePanel'
import { errorMessage } from './errorMessage'
import { ExtensionsPanel } from './ExtensionsPanel'
import { ModelServicePanel } from './ModelServicePanel'
import { ReflectionPanel } from './ReflectionPanel'
import { SecurityPanel } from './SecurityPanel'
import styles from './settings.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

export interface SettingsModalProps {
  open: boolean
  onClose: () => void
  /** 从状态栏更新徽标进入时直达「关于与更新」。 */
  initialPanel?: 'about'
}

/** 弹窗内可切换的面板；左侧导航里的可观测性项是跳转入口（独立页面），不属此列。 */
type PanelKey = 'model-service' | 'appearance' | 'reflection' | 'security' | 'extensions' | 'about'
type NavKey = PanelKey | 'observability'

/** 可观测性独立页面路由（内容唯一一份，弹窗内不再展开，MUST-10）。 */
const OBSERVABILITY_ROUTE = '/observability'

const NAV_KEYS: NavKey[] = [
  'model-service',
  'appearance',
  'reflection',
  'observability',
  'security',
  'extensions',
  'about',
]

/**
 * 导航项图标（2026-11-17：统一到 lucide 16px 线性体系，
 * 替掉原先的 ⚙ ◐ ◎ ⚑ 字符字形——字符在不同系统字体下大小与基线不一致）。
 */
const TAB_ICONS: Record<NavKey, typeof Settings> = {
  'model-service': Settings,
  appearance: Palette,
  reflection: Sparkles,
  observability: Activity,
  security: ShieldCheck,
  extensions: Plug,
  about: Info,
}

/** 渲染导航项图标（统一 16px 线性、currentColor，与全局图标体系一致）。 */
function NavIcon({ navKey }: { navKey: NavKey }): ReactNode {
  const Icon = TAB_ICONS[navKey]
  return <Icon size={16} strokeWidth={1.5} aria-hidden="true" />
}

/**
 * 设置中心模态（F-604）：左侧导航 + 右侧内容区；
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

  // 从状态栏更新徽标进入时直达「关于与更新」；用户手动切换后不再强制。
  useEffect(() => {
    if (props.open && props.initialPanel !== undefined) setActiveTab(props.initialPanel)
  }, [props.open, props.initialPanel])

  // 焦点陷阱：Tab 在弹窗内循环，不逃逸到背景（此前只移焦不循环）
  useFocusTrap(panelRef, props.open)

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
            <X size={16} strokeWidth={1.5} aria-hidden="true" />
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
                <NavIcon navKey={key} />
                {t(`settings.tab.${key}`)}
              </button>
            ))}
          </nav>
          <div className={s('settings-content')}>
            {loadError !== '' ? (
              <p className={s('settings-status settings-status--error')}>{loadError}</p>
            ) : null}
            {activeTab === 'model-service' ? <ModelServicePanel /> : null}
            {activeTab === 'appearance' ? <AppearancePanel /> : null}
            {activeTab === 'reflection' ? <ReflectionPanel /> : null}
            {activeTab === 'security' ? <SecurityPanel /> : null}
            {activeTab === 'extensions' ? <ExtensionsPanel /> : null}
            {activeTab === 'about' ? <AboutPanel /> : null}
          </div>
        </div>
      </div>
    </div>
  )
}
