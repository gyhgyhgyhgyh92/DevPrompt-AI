import { useEffect, useRef, useState } from 'react'
import { getSettings } from '../../api/endpoints'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { AppearancePanel } from './AppearancePanel'
import { errorMessage } from './errorMessage'
import { ModelServicePanel } from './ModelServicePanel'
import { SecurityPanel } from './SecurityPanel'
import './settings.css'

export interface SettingsModalProps {
  open: boolean
  onClose: () => void
}

type TabKey = 'model-service' | 'appearance' | 'security'

interface TabItem {
  key: TabKey
  icon: string
  label: string
}

const TABS: readonly TabItem[] = [
  { key: 'model-service', icon: '⚙', label: '模型服务' },
  { key: 'appearance', icon: '◐', label: '通用外观' },
  { key: 'security', icon: '⚑', label: '流程与安全' },
]

/**
 * 设置中心模态（F-604）：左侧四项导航 + 右侧内容区；
 * Esc/✕ 关闭，打开时焦点入面板、关闭归还触发按钮（无障碍惯例，非状态逻辑）。
 */
export function SettingsModal(props: SettingsModalProps) {
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
        if (!cancelled) setLoadError(errorMessage(error, '设置加载失败'))
      })
    return () => {
      cancelled = true
    }
  }, [props.open, setSettings])

  if (!props.open) return null

  return (
    <div className="settings-overlay">
      <div
        className="settings-modal"
        data-tab={activeTab}
        role="dialog"
        aria-modal="true"
        aria-label="设置"
        ref={panelRef}
        tabIndex={-1}
      >
        <header className="settings-modal__header">
          <h2 className="settings-modal__title">设置</h2>
          <button
            type="button"
            className="settings-close"
            aria-label="关闭"
            onClick={props.onClose}
          >
            ✕
          </button>
        </header>
        <div className="settings-modal__body">
          <nav className="settings-nav" aria-label="设置分组">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                type="button"
                aria-current={activeTab === tab.key ? 'page' : undefined}
                className={
                  activeTab === tab.key
                    ? 'settings-nav__item settings-nav__item--active'
                    : 'settings-nav__item'
                }
                onClick={() => setActiveTab(tab.key)}
              >
                {tab.icon} {tab.label}
              </button>
            ))}
          </nav>
          <div className="settings-content">
            {loadError !== '' ? (
              <p className="settings-status settings-status--error">{loadError}</p>
            ) : null}
            {activeTab === 'model-service' ? <ModelServicePanel /> : null}
            {activeTab === 'appearance' ? <AppearancePanel /> : null}
            {activeTab === 'security' ? <SecurityPanel /> : null}
          </div>
        </div>
      </div>
    </div>
  )
}
