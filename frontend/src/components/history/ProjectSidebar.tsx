import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { deleteHistory, getHistory, getResult, patchHistory } from '../../api/endpoints'
import type { HistoryItemPayload } from '../../api/types'
import { useOptimizeStore } from '../../stores/useOptimizeStore'
import { usePreferenceStore } from '../../stores/usePreferenceStore'
import { SessionMenu } from './SessionMenu'
import './ProjectSidebar.css'

/** 排序模式（顶部排序图标切换）：置顶优先（默认，与后端排序一致）/ 纯时间倒序。 */
type SortMode = 'pinned' | 'time'

/** toast 显示时长（自研轻量提示，2s 消失）。 */
const TOAST_DURATION_MS = 2000

function FolderIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M1.5 4a1 1 0 0 1 1-1h3l1.2 1.2h6.8a1 1 0 0 1 1 1V12a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V4Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
      />
    </svg>
  )
}

function PinIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M8 1.5 9.6 5l3.4.4-2.5 2.3.7 3.4L8 9.4l-3.2 1.7.7-3.4L3 5.4 6.4 5 8 1.5Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function DotIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <circle cx="8" cy="8" r="4" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  )
}

function SortIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M4 3v10M4 13l-2-2M4 13l2-2M12 13V3M12 3l-2 2M12 3l2 2"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function FilterIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M2 4h12M4 8h8M6.5 12h3"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
    </svg>
  )
}

/** 条目标题回退：无 custom_title 且无原句（旧数据）时拼「项目名 · 状态」（spec 假设 3）。 */
function itemTitle(item: HistoryItemPayload): string {
  return item.title !== '' ? item.title : `${item.project} · ${item.state}`
}

function sortItems(items: readonly HistoryItemPayload[], mode: SortMode): HistoryItemPayload[] {
  const copy = [...items]
  copy.sort((a, b) => {
    if (mode === 'pinned' && a.pinned !== b.pinned) return a.pinned ? -1 : 1
    return b.updated_at.localeCompare(a.updated_at)
  })
  return copy
}

/** 按项目分组（保持排序后首现顺序），组序由首条目决定。 */
function groupByProject(
  items: readonly HistoryItemPayload[],
): { project: string; items: HistoryItemPayload[] }[] {
  const groups: { project: string; items: HistoryItemPayload[] }[] = []
  for (const item of items) {
    const found = groups.find((group) => group.project === item.project)
    if (found) found.items.push(item)
    else groups.push({ project: item.project, items: [item] })
  }
  return groups
}

/**
 * 左侧固定侧边栏（图三 1:1，spec Task 4/5，F-602/F-703）。
 * 顶部「项目 ⌄」+ 排序/筛选图标；按项目分组渲染会话条目；选中同步高亮 + ⋮ 菜单（置顶/复制/重命名/删除）。
 * 数据自 GET /history（store 只存结果，MUST-16：数据获取在此组件 effect 内，不入 store）。
 */
export function ProjectSidebar() {
  const navigate = useNavigate()
  const history = usePreferenceStore((s) => s.history)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [sortMode, setSortMode] = useState<SortMode>('pinned')
  const [isGrouped, setGrouped] = useState(true)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [openMenuId, setOpenMenuId] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [toast, setToast] = useState<string | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    getHistory()
      .then((items) => usePreferenceStore.getState().setHistory(items))
      .catch(() => {
        // 列表加载失败保持空态，不重试（MUST-15）
      })
  }, [])

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
    if (items !== null) usePreferenceStore.getState().setHistory(items)
  }

  /** 选中：先同步高亮（乐观反馈 <100ms），再异步载入结果到主区（失败 toast 不取消高亮）。 */
  function handleSelect(sessionId: string): void {
    setSelectedId(sessionId)
    setOpenMenuId(null)
    navigate('/')
    getResult(sessionId)
      .then((snapshot) => useOptimizeStore.getState().applySnapshot(snapshot))
      .catch(() => showToast('会话结果加载失败'))
  }

  function handleNewSession(): void {
    useOptimizeStore.getState().reset()
    setSelectedId(null)
    setOpenMenuId(null)
    navigate('/')
  }

  async function handlePin(item: HistoryItemPayload): Promise<void> {
    setOpenMenuId(null)
    try {
      await patchHistory(item.session_id, { pinned: !item.pinned })
      await refreshHistory()
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
    } catch {
      showToast('重命名失败')
    }
  }

  async function handleDelete(item: HistoryItemPayload): Promise<void> {
    setOpenMenuId(null)
    try {
      await deleteHistory(item.session_id)
      await refreshHistory()
      if (selectedId === item.session_id) {
        useOptimizeStore.getState().reset()
        setSelectedId(null)
        navigate('/')
      }
    } catch {
      showToast('删除失败')
    }
  }

  /** 复制项目路径（GET /history 的 project 字段为项目名 basename，非全路径——见报告说明）。 */
  function handleCopyPath(item: HistoryItemPayload): void {
    setOpenMenuId(null)
    const text = item.project
    void navigator.clipboard
      .writeText(text)
      .then(() => showToast('已复制'))
      .catch(() => showToast('复制失败'))
  }

  const sorted = sortItems(history, sortMode)

  function renderRow(item: HistoryItemPayload) {
    const isSelected = selectedId === item.session_id
    const isMenuOpen = openMenuId === item.session_id
    const isRenaming = renamingId === item.session_id
    const showMenuButton = isSelected || hoveredId === item.session_id || isMenuOpen

    return (
      <li
        key={item.session_id}
        className={
          isSelected
            ? 'project-sidebar__item-row project-sidebar__item-row--selected'
            : 'project-sidebar__item-row'
        }
        onMouseEnter={() => setHoveredId(item.session_id)}
        onMouseLeave={() =>
          setHoveredId((current) => (current === item.session_id ? null : current))
        }
      >
        {isRenaming ? (
          <input
            className="project-sidebar__rename-input"
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
            className="project-sidebar__item"
            aria-current={isSelected ? 'true' : undefined}
            onClick={() => handleSelect(item.session_id)}
          >
            {isSelected ? (
              <span className="project-sidebar__item-icon">
                <DotIcon />
              </span>
            ) : null}
            <span className="project-sidebar__item-title">{itemTitle(item)}</span>
          </button>
        )}
        {item.pinned ? (
          <span className="project-sidebar__item-pin" aria-label="已置顶">
            <PinIcon />
          </span>
        ) : null}
        {showMenuButton ? (
          <button
            type="button"
            className="project-sidebar__menu-btn"
            aria-label="更多操作"
            onMouseDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation()
              setOpenMenuId((current) => (current === item.session_id ? null : item.session_id))
            }}
          >
            ⋮
          </button>
        ) : null}
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
  }

  return (
    <aside className="project-sidebar" aria-label="项目">
      <div className="project-sidebar__head">
        <span className="project-sidebar__title">
          项目
          <span aria-hidden="true">⌄</span>
        </span>
        <div className="project-sidebar__actions">
          <button
            type="button"
            className="project-sidebar__icon-btn"
            aria-label="排序"
            aria-pressed={sortMode === 'pinned'}
            onClick={() => setSortMode((mode) => (mode === 'pinned' ? 'time' : 'pinned'))}
          >
            <SortIcon />
          </button>
          <button
            type="button"
            className="project-sidebar__icon-btn"
            aria-label="筛选"
            aria-pressed={isGrouped}
            onClick={() => setGrouped((grouped) => !grouped)}
          >
            <FilterIcon />
          </button>
        </div>
      </div>

      <button type="button" className="project-sidebar__new" onClick={handleNewSession}>
        ＋ 新建会话
      </button>

      <div className="project-sidebar__list">
        {isGrouped ? (
          groupByProject(sorted).map((group) => (
            <section className="project-sidebar__group" key={group.project}>
              <div className="project-sidebar__group-head">
                <FolderIcon />
                <span>{group.project}</span>
              </div>
              <ul className="project-sidebar__items">{group.items.map(renderRow)}</ul>
            </section>
          ))
        ) : (
          <ul className="project-sidebar__items">{sorted.map(renderRow)}</ul>
        )}
        {history.length === 0 ? <p className="project-sidebar__empty">暂无历史会话</p> : null}
      </div>

      <nav className="project-sidebar__footer" aria-label="侧栏导航">
        <Link to="/history">历史记录 →</Link>
        <Link to="/preference">偏好记忆 →</Link>
      </nav>

      {toast !== null ? (
        <div className="project-sidebar__toast" role="status">
          {toast}
        </div>
      ) : null}
    </aside>
  )
}
