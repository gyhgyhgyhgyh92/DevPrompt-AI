import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { MoreVertical, Pin } from 'lucide-react'
import { Link, useNavigate } from 'react-router'
import {
  HISTORY_PAGE_SIZE,
  deleteHistory,
  getHistory,
  getResult,
  patchHistory,
} from '../api/endpoints'
import type { HistoryItemPayload } from '../api/types'
import { SessionMenu } from '../components/history/SessionMenu'
import { ConfirmDialog } from '../components/ui/ConfirmDialog'
import { useOptimizeStore } from '../stores/useOptimizeStore'
import { useHistoryStore } from '../stores/useHistoryStore'
import { formatDateTime } from '../utils/format'
import { useToast } from '../hooks/useToast'
import { Toast } from '../components/ui/Toast'
import styles from './HistoryPage.module.css'
import { makeS } from '../utils/css'

const s = makeS(styles)

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
  const { t } = useTranslation()
  const navigate = useNavigate()
  const history = useHistoryStore((s) => s.history)
  const hasMore = useHistoryStore((s) => s.hasMore)
  const [isLoading, setIsLoading] = useState(true)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [loadFailed, setLoadFailed] = useState(false)
  const [openMenuId, setOpenMenuId] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  // 删除确认（2026-11-01）：菜单只选目标，执行统一走 ConfirmDialog
  const [pendingDelete, setPendingDelete] = useState<HistoryItemPayload | null>(null)
  const [isDeleting, setDeleting] = useState(false)
  // 轻量提示：状态与计时收敛在共享 hook（2026-11-17），与侧栏共用同一份实现
  const toast = useToast()

  const load = useCallback(async () => {
    setIsLoading(true)
    setLoadFailed(false)
    try {
      const page = await getHistory({ limit: HISTORY_PAGE_SIZE })
      useHistoryStore.getState().setHistory(page.items, page.has_more)
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

  async function refreshHistory(): Promise<void> {
    const page = await getHistory({ limit: HISTORY_PAGE_SIZE }).catch(() => null)
    if (page !== null) {
      useHistoryStore.getState().setHistory(page.items, page.has_more)
    }
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

  /** 打开会话：载入结果到主区并回工作台（服务端为权威，MUST-07）。 */
  function handleOpen(sessionId: string): void {
    setOpenMenuId(null)
    navigate('/')
    getResult(sessionId)
      .then((snapshot) => useOptimizeStore.getState().applySnapshot(snapshot))
      .catch(() => toast.show(t('history.load_result_failed')))
  }

  async function handlePin(item: HistoryItemPayload): Promise<void> {
    setOpenMenuId(null)
    try {
      await patchHistory(item.session_id, { pinned: !item.pinned })
      await refreshHistory()
      toast.show(item.pinned ? t('history.unpinned') : t('history.pinned'))
    } catch {
      toast.show(t('history.pin_failed'))
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
      toast.show(t('history.renamed'))
    } catch {
      toast.show(t('history.rename_failed'))
    }
  }

  async function handleConfirmDelete(item: HistoryItemPayload): Promise<void> {
    setDeleting(true)
    try {
      await deleteHistory(item.session_id)
      // 删掉主区正打开的会话时复位流程状态，避免残留已删除会话的三套方案
      if (useOptimizeStore.getState().sessionId === item.session_id) {
        useOptimizeStore.getState().reset()
        navigate('/')
      }
      await refreshHistory()
      toast.show(t('history.deleted'))
    } catch {
      toast.show(t('history.delete_failed'))
    } finally {
      setDeleting(false)
      setPendingDelete(null)
    }
  }

  /** 复制项目路径：优先全路径 project_root，空则回退 project（旧数据）。 */
  function handleCopyPath(item: HistoryItemPayload): void {
    setOpenMenuId(null)
    const text = item.project_root !== '' ? item.project_root : item.project
    void navigator.clipboard
      .writeText(text)
      .then(() => toast.show(t('history.copied')))
      .catch(() => toast.show(t('history.copy_failed')))
  }

  const sorted = sortItems(history)

  return (
    <section className={s('workspace')}>
      <div className={s('workspace__thread')}>
        <div className={s('history-page__head')}>
          <h1>{t('history.title')}</h1>
          <Link to="/">{t('history.back_workbench')}</Link>
        </div>

        {isLoading ? <p className={s('context-panel__empty')}>{t('common.loading')}</p> : null}

        {!isLoading && loadFailed ? (
          <div className={s('history-page__notice')}>
            <p className={s('context-panel__empty')}>{t('history.load_failed_page')}</p>
            <button type="button" className={s('button')} onClick={() => void load()}>
              {t('common.reload')}
            </button>
          </div>
        ) : null}

        {!isLoading && !loadFailed ? (
          <>
            <ul className={s('variant-list')}>
              {sorted.map((item) => {
                const isRenaming = renamingId === item.session_id
                const isMenuOpen = openMenuId === item.session_id
                const isCurrent = useOptimizeStore.getState().sessionId === item.session_id

                return (
                  <li className={s('variant-card history-page__item')} key={item.session_id}>
                    {isRenaming ? (
                      <input
                        className={s('field__input')}
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
                        className={s('history-page__item-main')}
                        onClick={() => handleOpen(item.session_id)}
                      >
                        <span className={s('history-page__item-title')}>
                          {item.pinned ? (
                            <span
                              aria-label={t('history.pinned')}
                              className={s('history-page__pin')}
                            >
                              <Pin size={11} strokeWidth={1.5} aria-hidden="true" />
                            </span>
                          ) : null}
                          {itemTitle(item)}
                          {isCurrent ? (
                            <span className={s('history-page__tag')}>
                              {t('history.tag_current')}
                            </span>
                          ) : null}
                        </span>
                        <span className={s('history-page__item-meta')}>
                          <span className={s('session-sidebar__badge')}>{item.state}</span>
                          <span className={s('session-sidebar__project')}>
                            {projectName(item.project)}
                          </span>
                          <span>{formatDateTime(item.updated_at)}</span>
                        </span>
                      </button>
                    )}
                    <div className={s('history-page__actions')}>
                      <button
                        type="button"
                        className={s('button button--ghost')}
                        onClick={() => handleOpen(item.session_id)}
                      >
                        {t('common.open')}
                      </button>
                      <button
                        type="button"
                        className={s('button button--ghost')}
                        aria-label={t('history.aria_more')}
                        aria-expanded={isMenuOpen}
                        onClick={() =>
                          setOpenMenuId((current) =>
                            current === item.session_id ? null : item.session_id,
                          )
                        }
                      >
                        <MoreVertical size={14} strokeWidth={1.5} aria-hidden="true" />
                      </button>
                    </div>
                    {isMenuOpen ? (
                      <SessionMenu
                        isPinned={item.pinned}
                        onPin={() => void handlePin(item)}
                        onCopyPath={() => handleCopyPath(item)}
                        onRename={() => startRename(item)}
                        onDelete={() => {
                          setOpenMenuId(null)
                          setPendingDelete(item)
                        }}
                        onClose={() => setOpenMenuId(null)}
                      />
                    ) : null}
                  </li>
                )
              })}
            </ul>
            {hasMore ? (
              <button
                type="button"
                className={s('button button--ghost')}
                onClick={() => void loadMoreHistory()}
                disabled={isLoadingMore}
              >
                {isLoadingMore ? t('history.loading') : t('history.load_more')}
              </button>
            ) : null}
            {sorted.length === 0 ? (
              <p className={s('context-panel__empty')}>{t('history.empty')}</p>
            ) : null}
          </>
        ) : null}
      </div>

      {pendingDelete !== null ? (
        <ConfirmDialog
          title={t('history.confirm_delete_title')}
          description={`将删除「${itemTitle(pendingDelete)}」这条会话记录及其历史轮次，不会删除本地项目文件。`}
          confirmLabel={t('history.confirm_delete_title')}
          isBusy={isDeleting}
          onConfirm={() => void handleConfirmDelete(pendingDelete)}
          onClose={() => setPendingDelete(null)}
        />
      ) : null}

      <Toast message={toast.message} />
    </section>
  )
}
