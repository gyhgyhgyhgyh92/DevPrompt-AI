import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'
import {
  HISTORY_PAGE_SIZE,
  deleteHistory,
  deleteHistoryByProject,
  getHistory,
  getResult,
  patchHistory,
} from '../../api/endpoints'
import type { HistoryItemPayload } from '../../api/types'
import { useOptimizeStore } from '../../stores/useOptimizeStore'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { ConfirmDialog } from '../ui/ConfirmDialog'
import { SessionMenu } from './SessionMenu'
import styles from './ProjectSidebar.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

/** 排序：单一既定顺序——置顶优先，其次更新时间倒序（与后端排序口径一致）。 */
function sortItems(items: readonly HistoryItemPayload[]): HistoryItemPayload[] {
  const copy = [...items]
  copy.sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
    return b.updated_at.localeCompare(a.updated_at)
  })
  return copy
}

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

/** 一键收纳图标（图一）：竖向边界 + 左向双箭头（收起侧边栏语义，自绘 SVG，MUST-04）。 */
function CollapseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M13.5 3.5v9M9.5 4.5 6 8l3.5 3.5M5.5 4.5 2 8l3.5 3.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/** 项目组头删除图标（2026-11-01）：垃圾桶轮廓，与 SessionMenu 同形。 */
function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M3 4h10M6.5 4V2.8h3V4M4.3 4l.6 8.6h6.2L11.7 4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/** 条目标题回退：无 custom_title 且无原句（旧数据）时拼「项目名 · 状态」（spec 假设 3）。 */
function itemTitle(item: HistoryItemPayload): string {
  return item.title !== '' ? item.title : `${item.project} · ${item.state}`
}

/** 待确认的删除目标：单条会话或整个项目分组。 */
type PendingDelete =
  { kind: 'session'; item: HistoryItemPayload } | { kind: 'project'; group: ProjectGroup }

interface ProjectGroup {
  /** 项目全路径；老数据为空串（该组不支持批量删除）。 */
  projectRoot: string
  /** 目录名（组头展示）。 */
  project: string
  items: HistoryItemPayload[]
}

/**
 * 按项目**完整路径**分组（2026-11-01）：同名不同路径的目录不再合并，
 * 项目级删除的范围才精确。老数据无 project_root 时回退目录名。
 */
function groupByProject(items: readonly HistoryItemPayload[]): ProjectGroup[] {
  const groups = new Map<string, ProjectGroup>()
  for (const item of items) {
    const key = item.project_root !== '' ? item.project_root : item.project
    const found = groups.get(key)
    if (found) found.items.push(item)
    else groups.set(key, { projectRoot: item.project_root, project: item.project, items: [item] })
  }
  return [...groups.values()]
}

/**
 * 左侧固定侧边栏（图三 1:1，spec Task 4/5，F-602/F-703）。
 * 顶部「一键收纳按钮 + 项目」（2026-10-13：原 ⌄ 箭头替换为收纳、排序/筛选图标已移除；
 * 收纳按钮统一置左，与标题栏 ☰ 同侧，过渡由 global.css 宽度滑动 + 淡出实现）；
 * 列表恒按项目分组、置顶优先排序；选中同步高亮 + ⋮ 菜单（置顶/复制/重命名/删除）。
 * 数据自 GET /history（store 只存结果，MUST-16：数据获取在此组件 effect 内，不入 store）。
 */
interface ProjectSidebarProps {
  /** 一键收纳（F-602）：收起整个侧边栏（由外壳 App 接管折叠态与恢复入口）。 */
  onCollapse: () => void
  /** 选中/新建会话后的回调：窄屏据此收起抽屉（桌面态由外壳视作空操作）。 */
  onSelect: () => void
}

export function ProjectSidebar({ onCollapse, onSelect }: ProjectSidebarProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const history = useHistoryStore((s) => s.history)
  const hasMore = useHistoryStore((s) => s.hasMore)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [openMenuId, setOpenMenuId] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [toast, setToast] = useState<string | null>(null)
  // 删除确认（2026-11-01）：单条会话与整个项目共用同一个确认弹窗与请求中标志
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null)
  const [isDeleting, setDeleting] = useState(false)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    getHistory({ limit: HISTORY_PAGE_SIZE })
      .then((page) => useHistoryStore.getState().setHistory(page.items, page.has_more))
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
    const page = await getHistory({ limit: HISTORY_PAGE_SIZE }).catch(() => null)
    if (page !== null) useHistoryStore.getState().setHistory(page.items, page.has_more)
  }

  /** 加载更早的会话（分页增量合并，取代 50 条硬顶）。 */
  async function loadMoreHistory(): Promise<void> {
    const store = useHistoryStore.getState()
    if (!store.hasMore) return
    setIsLoadingMore(true)
    try {
      const page = await getHistory({
        limit: HISTORY_PAGE_SIZE,
        offset: store.history.length,
      })
      store.appendHistory(page.items, page.has_more)
    } catch {
      // 失败保持原列表，用户可再次点击（不自动重试，MUST-15）
    } finally {
      setIsLoadingMore(false)
    }
  }

  /** 选中：先同步高亮（乐观反馈 <100ms），再异步载入结果到主区（失败 toast 不取消高亮）。 */
  function handleSelect(sessionId: string): void {
    onSelect()
    setSelectedId(sessionId)
    setOpenMenuId(null)
    navigate('/')
    getResult(sessionId)
      .then((snapshot) => useOptimizeStore.getState().applySnapshot(snapshot))
      .catch(() => showToast(t('history.load_result_failed')))
  }

  function handleNewSession(): void {
    onSelect()
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
      showToast(t('history.pin_failed'))
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
      showToast(t('history.rename_failed'))
    }
  }

  /** 单条会话删除：确认弹窗点「删除会话」后才发请求（2026-11-01 统一确认形态）。 */
  async function deleteSession(item: HistoryItemPayload): Promise<void> {
    await deleteHistory(item.session_id)
    if (selectedId === item.session_id) {
      useOptimizeStore.getState().reset()
      setSelectedId(null)
      navigate('/')
    }
    await refreshHistory()
  }

  /** 项目级删除：按 project_root 批量删该组会话记录，磁盘项目文件不动，返回删除条数。 */
  async function deleteProject(group: ProjectGroup): Promise<number> {
    const deleted = await deleteHistoryByProject(group.projectRoot)
    // 删掉的正是主区打开的会话 → 复位，避免残留已删除会话的方案
    const activeSessionId = useOptimizeStore.getState().sessionId
    const hitActive =
      activeSessionId !== null && group.items.some((entry) => entry.session_id === activeSessionId)
    if (hitActive) {
      useOptimizeStore.getState().reset()
      setSelectedId(null)
      navigate('/')
    }
    await refreshHistory()
    return deleted
  }

  /** 确认弹窗统一入口：按目标类型分派；失败只提示不重试（MUST-15）。 */
  async function handleConfirmDelete(): Promise<void> {
    const target = pendingDelete
    if (target === null) return
    setDeleting(true)
    try {
      if (target.kind === 'session') {
        await deleteSession(target.item)
        showToast(t('history.deleted'))
      } else {
        const deleted = await deleteProject(target.group)
        showToast(`已删除 ${deleted} 条会话`)
      }
    } catch {
      showToast(
        target.kind === 'session' ? t('history.delete_failed') : t('history.delete_project_failed'),
      )
    } finally {
      setDeleting(false)
      setPendingDelete(null)
    }
  }

  /** 复制项目路径：优先全路径 project_root，空则回退 basename（project，旧数据）。 */
  function handleCopyPath(item: HistoryItemPayload): void {
    setOpenMenuId(null)
    const text = item.project_root !== '' ? item.project_root : item.project
    void navigator.clipboard
      .writeText(text)
      .then(() => showToast(t('history.copied')))
      .catch(() => showToast(t('history.copy_failed')))
  }

  const sorted = sortItems(history)

  function renderRow(item: HistoryItemPayload) {
    const isSelected = selectedId === item.session_id
    const isMenuOpen = openMenuId === item.session_id
    const isRenaming = renamingId === item.session_id
    const showMenuButton = isSelected || hoveredId === item.session_id || isMenuOpen

    return (
      <li
        key={item.session_id}
        className={s(
          isSelected
            ? 'project-sidebar__item-row project-sidebar__item-row--selected'
            : 'project-sidebar__item-row',
        )}
        onMouseEnter={() => setHoveredId(item.session_id)}
        onMouseLeave={() =>
          setHoveredId((current) => (current === item.session_id ? null : current))
        }
      >
        {isRenaming ? (
          <input
            className={s('project-sidebar__rename-input')}
            aria-label={t('history.aria_rename')}
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
            className={s('project-sidebar__item')}
            aria-current={isSelected ? 'true' : undefined}
            onClick={() => handleSelect(item.session_id)}
          >
            {isSelected ? (
              <span className={s('project-sidebar__item-icon')}>
                <DotIcon />
              </span>
            ) : null}
            <span className={s('project-sidebar__item-title')}>{itemTitle(item)}</span>
          </button>
        )}
        {item.pinned ? (
          <span className={s('project-sidebar__item-pin')} aria-label={t('history.pinned')}>
            <PinIcon />
          </span>
        ) : null}
        {showMenuButton ? (
          <button
            type="button"
            className={s('project-sidebar__menu-btn')}
            aria-label={t('history.aria_more')}
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
            onDelete={() => {
              setOpenMenuId(null)
              setPendingDelete({ kind: 'session', item })
            }}
            onClose={() => setOpenMenuId(null)}
          />
        ) : null}
      </li>
    )
  }

  return (
    <aside className={s('project-sidebar')} aria-label={t('history.sidebar_label')}>
      <div className={s('project-sidebar__head')}>
        <button
          type="button"
          className={s('project-sidebar__collapse')}
          aria-label={t('history.aria_collapse')}
          onClick={onCollapse}
        >
          <CollapseIcon />
        </button>
        <span className={s('project-sidebar__title')}>{t('history.sidebar_label')}</span>
      </div>

      <button type="button" className={s('project-sidebar__new')} onClick={handleNewSession}>
        ＋ 新建会话
      </button>

      <div className={s('project-sidebar__list')}>
        {groupByProject(sorted).map((group) => (
          <section className={s('project-sidebar__group')} key={group.projectRoot || group.project}>
            {/* title 用全路径：同名不同路径的项目靠悬停区分 */}
            <div
              className={s('project-sidebar__group-head')}
              title={group.projectRoot || undefined}
            >
              <FolderIcon />
              <span className={s('project-sidebar__group-name')}>{group.project}</span>
              {group.projectRoot !== '' ? (
                <button
                  type="button"
                  className={s('project-sidebar__group-delete')}
                  aria-label={`删除项目 ${group.project}`}
                  onClick={() => {
                    setOpenMenuId(null)
                    setPendingDelete({ kind: 'project', group })
                  }}
                >
                  <TrashIcon />
                </button>
              ) : null}
            </div>
            <ul className={s('project-sidebar__items')}>{group.items.map(renderRow)}</ul>
          </section>
        ))}
        {hasMore ? (
          <button
            type="button"
            className={s('button button--ghost project-sidebar__more')}
            onClick={() => void loadMoreHistory()}
            disabled={isLoadingMore}
          >
            {isLoadingMore ? t('history.loading') : t('history.load_more')}
          </button>
        ) : null}
        {history.length === 0 ? (
          <p className={s('project-sidebar__empty')}>{t('history.empty_sessions')}</p>
        ) : null}
      </div>

      <nav className={s('project-sidebar__footer')} aria-label={t('history.footer_nav')}>
        <Link to="/history">{t('history.link_history')}</Link>
      </nav>

      {toast !== null ? (
        <div className={s('project-sidebar__toast')} role="status">
          {toast}
        </div>
      ) : null}

      {/* Portal 到 body：窄屏抽屉的 transform 会成为 fixed 的包含块，弹窗会被裁在抽屉里 */}
      {pendingDelete !== null
        ? createPortal(
            <ConfirmDialog
              title={
                pendingDelete.kind === 'session'
                  ? t('history.confirm_delete_title')
                  : t('history.confirm_delete_project')
              }
              description={
                pendingDelete.kind === 'session'
                  ? `将删除「${itemTitle(pendingDelete.item)}」这条会话记录及其历史轮次，不会删除本地项目文件。`
                  : `将删除「${pendingDelete.group.project}」下全部 ${pendingDelete.group.items.length} 条会话记录（含置顶与历史轮次），不会删除本地项目文件。`
              }
              confirmLabel={
                pendingDelete.kind === 'session'
                  ? t('history.confirm_delete_title')
                  : t('history.confirm_delete_project')
              }
              isBusy={isDeleting}
              onConfirm={() => void handleConfirmDelete()}
              onClose={() => setPendingDelete(null)}
            />,
            document.body,
          )
        : null}
    </aside>
  )
}
