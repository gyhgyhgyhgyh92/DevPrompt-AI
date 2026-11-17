import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BrowserRouter } from 'react-router'
import { getHealth, getSettings } from './api/endpoints'
import { ProjectSidebar } from './components/history/ProjectSidebar'
import { SettingsModal } from './components/settings/SettingsModal'
import { BrandMark } from './components/ui/BrandMark'
import { AppRoutes } from './router'
import { applyLocale } from './i18n'
import { useOptimizeStore } from './stores/useOptimizeStore'
import { useHistoryStore } from './stores/useHistoryStore'
import { applyAppearanceTheme, useSettingsStore, watchSystemTheme } from './stores/useSettingsStore'
import { makeS } from './utils/css'
import styles from './App.module.css'

const s = makeS(styles)

type ApiStatus = 'checking' | 'ok' | 'down'

/** GET /health 里代表「API 可用性」的检查项名（后端检查项标识，非前端判定）。 */
const LLM_CHECK_NAME = 'llm_config'

const API_STATUS_KEY: Record<ApiStatus, string> = {
  checking: 'app.status_checking',
  ok: 'app.status_ok',
  down: 'app.status_down',
}

/** 设置入口图标（线性齿轮；避免 ⚙ 字符在不同系统字体下大小与基线不一致）。 */
function GearIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <circle cx="8" cy="8" r="2.3" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path
        d="M8 1.5v1.7M8 12.8v1.7M1.5 8h1.7M12.8 8h1.7M3.4 3.4l1.2 1.2M11.4 11.4l1.2 1.2M12.6 3.4l-1.2 1.2M4.6 11.4l-1.2 1.2"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
    </svg>
  )
}

/**
 * 根组件 + 路由表 + 工作台壳层（标题栏 / 内容 / 状态栏，设计文档 §1.1）。
 * 6B 承诺：T6-4 页面落地后切 BrowserRouter，恢复 URL 直达与刷新定位。
 */
export function App() {
  const { t } = useTranslation()
  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking')
  const [isSettingsOpen, setSettingsOpen] = useState(false)
  // 窄屏（<768）侧边栏抽屉开合；纯表现层状态，不进 store，不含任何业务判定（MUST-07/08）
  const [isDrawerOpen, setDrawerOpen] = useState(false)
  // 一键收纳（F-602，2026-10-13）：桌面端收起整个侧边栏；与抽屉共用同一状态位（窄屏=关抽屉）
  const [isSidebarCollapsed, setSidebarCollapsed] = useState(false)
  // 只订阅标题栏真正用到的一个字段（MUST-16：精确 selector，不整表订阅）
  const sessionId = useOptimizeStore((s) => s.sessionId)
  const history = useHistoryStore((s) => s.history)
  const setSettings = useSettingsStore((s) => s.setSettings)
  const locale = useSettingsStore((s) => s.appearance.locale)
  const theme = useSettingsStore((s) => s.appearance.theme)

  // 界面语言即时生效（2026-11-06 多语言）：appearance.locale 是唯一真源
  useEffect(() => {
    applyLocale(locale)
  }, [locale])

  // 主题即时生效（2026-11-06）：刷新后必须按偏好重新应用（此前只写 index.html 的 light），
  // system 模式还要跟随系统深色切换，故 apply + watch 成对出现，返回值即取消订阅。
  useEffect(() => {
    applyAppearanceTheme(theme)
    return watchSystemTheme()
  }, [theme])

  // 标题栏 API pill 数据源（GET /health）；失败即降级为「API 异常」，不重试（MUST-15）
  //
  // 只看 **llm_config** 那项，不看 is_healthy：pill 的文案声明的是「API 状态」，
  // 而 is_healthy 是**全系统**健康度——ripgrep 缺失、DB 被锁等无关故障都会把它压成
  // false，于是明明密钥与端点都好却显示「API 异常」，只把人引向错误的排查方向。
  useEffect(() => {
    let isCancelled = false
    getHealth()
      .then((health) => {
        if (isCancelled) return
        const llm = health.checks.find((item) => item.name === LLM_CHECK_NAME)
        setApiStatus(llm?.ok === true ? 'ok' : 'down')
      })
      .catch(() => {
        if (!isCancelled) setApiStatus('down')
      })
    return () => {
      isCancelled = true
    }
  }, [])

  // 设置预加载（2026-11-03）：启动页/结果页的模型选择器只读 store，此前仅打开设置弹窗才加载，
  // 于是进入页面恒显示「未配置模型」且下拉被禁用（后端 active_model_id 其实一直正常）。
  // 失败保持 null 不重试（MUST-15），设置面板打开时仍会再取一次。
  useEffect(() => {
    let isCancelled = false
    getSettings()
      .then((next) => {
        if (!isCancelled) setSettings(next)
      })
      .catch(() => undefined)
    return () => {
      isCancelled = true
    }
  }, [setSettings])

  // 抽屉打开时 Esc 关闭（无障碍要求；关闭后移除监听）
  useEffect(() => {
    if (!isDrawerOpen) return undefined
    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key === 'Escape') setDrawerOpen(false)
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isDrawerOpen])

  const activeProject =
    sessionId === null ? undefined : history.find((item) => item.session_id === sessionId)?.project

  /** 窄屏判定（jsdom 无 matchMedia 时兜底 false，沿用项目既有防御先例）。 */
  function isNarrowViewport(): boolean {
    return (
      typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 767px)').matches
    )
  }

  /** 标题栏 ☰：桌面端折叠时展开；否则唤出窄屏抽屉。 */
  function handleMenuClick(): void {
    if (!isNarrowViewport() && isSidebarCollapsed) setSidebarCollapsed(false)
    else setDrawerOpen(true)
  }

  /** 侧边栏一键收纳：关闭窄屏抽屉并置折叠态（桌面收起、窄屏等价关抽屉）。 */
  function handleCollapse(): void {
    setDrawerOpen(false)
    setSidebarCollapsed(true)
  }

  return (
    <BrowserRouter>
      <div
        className={s(isSidebarCollapsed ? 'app-shell app-shell--sidebar-collapsed' : 'app-shell')}
        data-shell
      >
        <header className={s('app-titlebar')} data-titlebar>
          <button
            type="button"
            className={s('app-titlebar__menu')}
            aria-label={t('app.open_sidebar')}
            aria-expanded={isDrawerOpen}
            onClick={handleMenuClick}
          >
            ☰
          </button>
          <span className={s('app-titlebar__logo')}>
            <BrandMark size={18} />
            DevPrompt AI
          </span>
          <span className={s('app-titlebar__chip')}>{activeProject ?? t('app.no_project')}</span>
          <span className={s('app-titlebar__spacer')} />
          <span className={s(`api-pill api-pill--${apiStatus}`)}>
            <span className={s('api-pill__dot')} aria-hidden="true" />
            {t(API_STATUS_KEY[apiStatus])}
          </span>
          <button
            type="button"
            className={s('app-titlebar__settings')}
            aria-label={t('app.settings')}
            title={t('app.settings')}
            onClick={() => setSettingsOpen(true)}
          >
            <GearIcon />
            <span>{t('app.settings')}</span>
          </button>
        </header>
        <div className={s('app-body')} data-body>
          <div
            className={s(isDrawerOpen ? 'app-drawer app-drawer--open' : 'app-drawer')}
            data-drawer
          >
            <ProjectSidebar onCollapse={handleCollapse} onSelect={() => setDrawerOpen(false)} />
          </div>
          {isDrawerOpen ? (
            <button
              type="button"
              className={s('app-drawer__overlay')}
              data-drawer-overlay
              aria-label={t('app.close_sidebar')}
              onClick={() => setDrawerOpen(false)}
            />
          ) : null}
          <main className={s('app-main')} data-main>
            <AppRoutes />
          </main>
        </div>
      </div>
      <SettingsModal open={isSettingsOpen} onClose={() => setSettingsOpen(false)} />
    </BrowserRouter>
  )
}
