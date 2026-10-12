import { useEffect, useState } from 'react'
import { BrowserRouter } from 'react-router'
import { useShallow } from 'zustand/react/shallow'
import { getHealth } from './api/endpoints'
import { ProjectSidebar } from './components/history/ProjectSidebar'
import { SettingsModal } from './components/settings/SettingsModal'
import { AppRoutes } from './router'
import { useOptimizeStore } from './stores/useOptimizeStore'
import { usePreferenceStore } from './stores/usePreferenceStore'

type ApiStatus = 'checking' | 'ok' | 'down'

const API_STATUS_TEXT: Record<ApiStatus, string> = {
  checking: 'API 检测中',
  ok: 'API 正常',
  down: 'API 异常',
}

/**
 * 根组件 + 路由表 + 工作台壳层（标题栏 / 内容 / 状态栏，设计文档 §1.1）。
 * 6B 承诺：T6-4 页面落地后切 BrowserRouter，恢复 URL 直达与刷新定位。
 */
export function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking')
  const [isSettingsOpen, setSettingsOpen] = useState(false)
  const { sessionId, state, sseStatus } = useOptimizeStore(
    useShallow((s) => ({ sessionId: s.sessionId, state: s.state, sseStatus: s.sseStatus })),
  )
  const history = usePreferenceStore((s) => s.history)

  // 标题栏 API pill 数据源（GET /health）；失败即降级为「API 异常」，不重试（MUST-15）
  useEffect(() => {
    let isCancelled = false
    getHealth()
      .then((health) => {
        if (!isCancelled) setApiStatus(health.is_healthy ? 'ok' : 'down')
      })
      .catch(() => {
        if (!isCancelled) setApiStatus('down')
      })
    return () => {
      isCancelled = true
    }
  }, [])

  const activeProject =
    sessionId === null ? undefined : history.find((item) => item.session_id === sessionId)?.project

  return (
    <BrowserRouter>
      <div className="app-shell">
        <header className="app-titlebar">
          <span className="app-titlebar__logo">● DevPrompt AI</span>
          <span className="app-titlebar__chip">
            {activeProject ? `▸ ${activeProject}` : '▸ 未选择项目'}
          </span>
          <span className="app-titlebar__spacer" />
          <span className={`api-pill api-pill--${apiStatus}`}>
            <span className="api-pill__dot" aria-hidden="true" />
            {API_STATUS_TEXT[apiStatus]}
          </span>
          <button
            type="button"
            className="button button--ghost"
            onClick={() => setSettingsOpen(true)}
          >
            ⚙ 设置
          </button>
        </header>
        <div className="app-body">
          <ProjectSidebar />
          <main className="app-main">
            <AppRoutes />
          </main>
        </div>
        <footer className="app-statusbar">
          <span>session: {sessionId ?? '无'}</span>
          <span>state: {state}</span>
          <span>SSE: {sseStatus}</span>
        </footer>
      </div>
      <SettingsModal open={isSettingsOpen} onClose={() => setSettingsOpen(false)} />
    </BrowserRouter>
  )
}
