import { Link } from 'react-router'
import type { HistoryItemPayload } from '../../api/types'
import { truncate } from '../../utils/format'

interface SessionSidebarProps {
  sessions: readonly HistoryItemPayload[]
  onSelectSession: (sessionId: string) => void
  onNewSession: () => void
}

/** 项目名展示：路径取末段（时间展示用 utils/format，此处不引新依赖）。 */
function projectName(project: string): string {
  return project.split(/[\\/]/).filter(Boolean).pop() ?? project
}

/** 侧栏空间有限，session_id 仅展示前缀便于辨识（截短长度为展示约定，非业务约束）。 */
const SESSION_ID_DISPLAY_CHARS = 8

export function SessionSidebar({ sessions, onSelectSession, onNewSession }: SessionSidebarProps) {
  return (
    <aside className="session-sidebar" aria-label="会话侧栏">
      <button type="button" className="button button--primary" onClick={onNewSession}>
        ＋ 新建会话
      </button>
      <h2>历史会话</h2>
      <ul className="session-sidebar__list">
        {sessions.map((item) => (
          <li key={item.session_id}>
            <button
              type="button"
              className="session-sidebar__item"
              onClick={() => onSelectSession(item.session_id)}
            >
              <span className="session-sidebar__id">
                {truncate(item.session_id, SESSION_ID_DISPLAY_CHARS)}
              </span>
              <span className="session-sidebar__badge">{item.state}</span>
              <span className="session-sidebar__project">{projectName(item.project)}</span>
            </button>
          </li>
        ))}
      </ul>
      {sessions.length === 0 ? <p className="context-panel__empty">暂无历史会话</p> : null}
      <nav className="session-sidebar__footer" aria-label="侧栏导航">
        <Link to="/history">历史记录 →</Link>
        <Link to="/preference">偏好记忆 →</Link>
      </nav>
    </aside>
  )
}
