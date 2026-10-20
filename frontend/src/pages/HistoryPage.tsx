import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { deleteHistory, getHistory, getResult, patchHistory } from '../api/endpoints'
import type { HistoryItemPayload } from '../api/types'
import { SessionMenu } from '../components/history/SessionMenu'
import { useOptimizeStore } from '../stores/useOptimizeStore'
import { useHistoryStore } from '../stores/useHistoryStore'
import { formatDateTime } from '../utils/format'
import './HistoryPage.css'

/** 排序：置顶优先，其次更新时间倒序（与 ProjectSidebar 同口径；仅展示序，非业务判定）。 */
function sortItems(items: readonly HistoryItemPayload[]): HistoryItemPayload[] {
  return [...items].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
    return b.updated_at.localeCompare(a.updated_at)
  })
}

/** 条目标题：无自定义标题（旧数据）时回退「项目名 · 状态」。 */
function itemTitle(item: HistoryItemPayload): string {
  return item.title !== '' ? item.title : `${item.project} · ${item.state}`
}

/** 项目名展示：路径取末段（与会话侧栏同口径）。 */
function projectName(project: string): string {
  return project.split(/[\\/]/).filter(Boolean).pop() ?? project
}

/** toast 显示时长（自研轻量提示）。 */
const TOAST_DURATION_MS = 2000

/**
 * 历史记录页（F-702 独立可用）：列表 + 置顶 / 重命名 / 删除 / 复制路径 / 打开会话。
 *
 * 2026-10-16 补全：此前仅骨架只读，全部管理操作只能在侧栏或设置中心完成。
 * 现在复用既有 `PATCH/DELETE /history/{id}` 契约与 `SessionMenu`，
 * **本页面不依赖侧栏或设置中心即可完成全部会话管理**。
 *
 * 边界：仅做「参数收拢 → 调 api → 渲染」，零业务判定（MUST-08/10）；
 * 状态以服务端为权威，每次写操作后 `refreshHistory()` 重新拉取；
 * 有副作用端点禁自动重试（MUST-15）。
 */
export function HistoryPage() {
  const navigate = useNavigate()
  const history = useHistoryStore((s) => s.history)
  const [isLoading, setIsLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [openMenuId, setOpenMenuId] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [toast, setToast] = useState<string | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const load = useCallback(async () => {
    setIsLoading(true)
    setLoadFailed(false)
    try {
      const items = await getHistory()
      useHistoryStore.getState().setHistory(items)
    } catch {
      // 加载失败保留空态 + 显式失败提示，不自动重试（MUST-15）
      setLoadFailed(true)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(
    () => () => {
      if (toastTimer.current !== null) clearTimeout(toastTimer.current)
    },
    [],
  )

  function showToast(text: string): void {
    setToast(text)
    if (toastTimer.current !== null) clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS)
  }

  async function refreshHistory(): Promise<void> {
    const items = await getHistory().catch(() => null)
    if (items !== null) useHistoryStore.getState().setHistory(items)
  }

  /** 打开会话：载入结果到主区并回工作台（服务端为权威，MUST-07）。 */
  function handleOpen(sessionId: string): void {
    setOpenMenuId(null)
    navigate('/')
    getResult(sessionId)
      .then((snapshot) => useOptimizeStore.getState().applySnapshot(snapshot))
      .catch(() => showToast('会话结果加载失败'))
  }

  async function handlePin(item: HistoryItemPayload): Promise<void> {
    setOpenMenuId(null)
    try {
      await patchHistory(item.session_id, { pinned: !item.pinned })
      await refreshHistory()
      showToast(item.pinned ? '已取消置顶' : '已置顶')
    } catch {
      showToast('置顶操作失败')
    }
  }

  function startRename(item: HistoryItemPayload): void {
    setOpenMenuId(null)
    setRenamingId(item.session_id)
    setRenameDraft(itemTitle(item))
  }

  async function submitRename(item: HistoryItemPayload): Promise<void> {
    const title = renameDraft.trim()
    setRenamingId(null)
    if (title === '' || title === itemTitle(item)) return
    try {
      await patchHistory(item.session_id, { title })
      await refreshHistory()
      showToast('已重命名')
    } catch {
      showToast('重命名失败')
    }
  }

  async function handleDelete(item: HistoryItemPayload): Promise<void> {
    setOpenMenuId(null)
    try {
      await deleteHistory(item.session_id)
      // 删掉主区正打开的会话时复位流程状态，避免残留已删除会话的三套方案
      if (useOptimizeStore.getState().sessionId === item.session_id) {
        useOptimizeStore.getState().reset()
        navigate('/')
      }
      await refreshHistory()
      showToast('已删除')
    } catch {
      showToast('删除失败')
    }
  }

  /** 复制项目路径：优先全路径 project_root，空则回退 project（旧数据）。 */
  function handleCopyPath(item: HistoryItemPayload): void {
    setOpenMenuId(null)
    const text = item.project_root !== '' ? item.project_root : item.project
    void navigator.clipboard
      .writeText(text)
      .then(() => showToast('已复制'))
      .catch(() => showToast('复制失败'))
  }

  const sorted = sortItems(history)

  return (
    <section className="workspace">
      <div className="workspace__thread">
        <div className="history-page__head">
          <h1>历史记录</h1>
          <Link to="/">← 工作台</Link>
        </div>

        {isLoading ? <p className="context-panel__empty">加载中…</p> : null}

        {!isLoading && loadFailed ? (
          <div className="history-page__notice">
            <p className="context-panel__empty">历史记录加载失败，请检查服务是否运行。</p>
            <button type="button" className="button" onClick={() => void load()}>
              重新加载
            </button>
          </div>
        ) : null}

        {!isLoading && !loadFailed ? (
          <>
            <ul className="variant-list">
              {sorted.map((item) => {
                const isRenaming = renamingId === item.session_id
                const isMenuOpen = openMenuId === item.session_id
                const isCurrent = useOptimizeStore.getState().sessionId === item.session_id

                return (
                  <li className="variant-card history-page__item" key={item.session_id}>
                    {isRenaming ? (
                      <input
                        className="field__input"
                        aria-label="重命名会话"
                        value={renameDraft}
                        autoFocus
                        onChange={(event) => setRenameDraft(event.currentTarget.value)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') void submitRename(item)
                          if (event.key === 'Escape') setRenamingId(null)
                        }}
                        onBlur={() => void submitRename(item)}
                      />
                    ) : (
                      <button
                        type="button"
                        className="history-page__item-main"
                        onClick={() => handleOpen(item.session_id)}
                      >
                        <span className="history-page__item-title">
                          {item.pinned ? <span aria-label="已置顶">📌 </span> : null}
                          {itemTitle(item)}
                          {isCurrent ? <span className="history-page__tag">进行中</span> : null}
                        </span>
                        <span className="history-page__item-meta">
                          <span className="session-sidebar__badge">{item.state}</span>
                          <span className="session-sidebar__project">
                            {projectName(item.project)}
                          </span>
                          <span>{formatDateTime(item.updated_at)}</span>
                        </span>
                      </button>
                    )}
                    <div className="history-page__actions">
                      <button
                        type="button"
                        className="button button--ghost"
                        onClick={() => handleOpen(item.session_id)}
                      >
                        打开
                      </button>
                      <button
                        type="button"
                        className="button button--ghost"
                        aria-label="更多操作"
                        aria-expanded={isMenuOpen}
                        onClick={() =>
                          setOpenMenuId((current) =>
                            current === item.session_id ? null : item.session_id,
                          )
                        }
                      >
                        ⋮
                      </button>
                    </div>
                    {isMenuOpen ? (
                      <SessionMenu
                        isPinned={item.pinned}
                        onPin={() => void handlePin(item)}
                        onCopyPath={() => handleCopyPath(item)}
                        onRename={() => startRename(item)}
                        onDelete={() => void handleDelete(item)}
                        onClose={() => setOpenMenuId(null)}
                      />
                    ) : null}
                  </li>
                )
              })}
            </ul>
            {sorted.length === 0 ? <p className="context-panel__empty">暂无历史记录</p> : null}
          </>
        ) : null}
      </div>

      {toast !== null ? (
        <div className="project-sidebar__toast" role="status">
          {toast}
        </div>
      ) : null}
    </section>
  )
}
