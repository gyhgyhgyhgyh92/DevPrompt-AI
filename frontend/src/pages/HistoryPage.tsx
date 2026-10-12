import { useEffect } from 'react'
import { Link } from 'react-router'
import { getHistory } from '../api/endpoints'
import { usePreferenceStore } from '../stores/usePreferenceStore'
import { formatDateTime } from '../utils/format'

/** 项目名展示：路径取末段（与会话侧栏同口径）。 */
function projectName(project: string): string {
  return project.split(/[\\/]/).filter(Boolean).pop() ?? project
}

/** 历史记录页（F-702）：GET /history 列表骨架接数据；编辑/清空等操作归设置中心。 */
export function HistoryPage() {
  const history = usePreferenceStore((s) => s.history)

  useEffect(() => {
    getHistory()
      .then((items) => usePreferenceStore.getState().setHistory(items))
      .catch(() => {
        // 列表加载失败保持空态，不重试（MUST-15）
      })
  }, [])

  return (
    <section className="workspace">
      <div className="workspace__thread">
        <h1>历史记录</h1>
        <Link to="/">← 工作台</Link>
        <ul className="variant-list">
          {history.map((item) => (
            <li className="variant-card" key={item.session_id}>
              <span>{formatDateTime(item.updated_at)}</span>
              <span className="session-sidebar__badge">{item.state}</span>
              <span className="session-sidebar__project">{projectName(item.project)}</span>
            </li>
          ))}
        </ul>
        {history.length === 0 ? <p className="context-panel__empty">暂无历史记录</p> : null}
      </div>
    </section>
  )
}
