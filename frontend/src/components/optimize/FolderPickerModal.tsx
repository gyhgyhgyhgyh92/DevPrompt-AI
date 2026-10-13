import { useEffect, useRef, useState } from 'react'
import { getBrowse } from '../../api/endpoints'
import type { BrowseEntryPayload, BrowseResponse } from '../../api/types'
import './FolderPickerModal.css'

export interface FolderPickerModalProps {
  open: boolean
  /** 打开时优先浏览的目录（通常为已选项目路径；空串则从驱动器列表开始）。 */
  initialPath: string
  onSelect: (path: string) => void
  onClose: () => void
}

/** 触屏（coarse pointer）单击即进入目录；鼠标语义单击选中、双击进入（触屏无 dblclick）。 */
function isCoarsePointer(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(pointer: coarse)').matches
}

/** 日期格式化（后端本地 ISO 秒精度 → `YYYY/MM/DD HH:mm`；字符串切分，不走 Date 解析避时区偏移）。 */
export function formatDateTime(iso: string | null): string {
  if (iso === null || iso.length < 16) return ''
  return `${iso.slice(0, 10).replaceAll('-', '/')} ${iso.slice(11, 16)}`
}

/** 面包屑分段（纯展示）：path='' → 仅「此电脑」；否则「此电脑」+ 路径分段。 */
function breadcrumbSegments(path: string): string[] {
  if (path === '') return ['此电脑']
  return ['此电脑', ...path.split(/[\\/]+/).filter(Boolean)]
}

/** 分段 → 目标路径：首段回驱动器列表；`D:` 段为 `D:\`；其余按序以 `\` 拼接。 */
function segmentTarget(segments: string[], index: number): string {
  if (index === 0) return ''
  const parts = segments.slice(1, index + 1)
  const head = parts[0]
  if (head === undefined) return ''
  if (parts.length === 1) return `${head}\\`
  return `${head}\\${parts.slice(1).join('\\')}`
}

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

/**
 * 页内文件夹选择器（F-601「选择文件夹（本地）」，Win11 风格复刻）：完全嵌入浏览器页面
 * （DOM 模态，属于页面视口），不弹系统桌面窗口。浏览器沙箱禁读本地绝对路径，目录条目
 * （名称 + 修改日期；仅目录，文件不出现——用户裁定）由后端 GET /project/browse 提供；
 * 排序（名称升序）由后端固定。
 * 交互：后退/前进/上级 + 地址栏面包屑跳转；单击选中（触屏单击即进入）、双击进入；
 * Esc/✕ 关闭、焦点入面板并归还；确认返回当前所在目录。
 */
export function FolderPickerModal(props: FolderPickerModalProps) {
  const { open, initialPath, onSelect, onClose } = props
  const [listing, setListing] = useState<BrowseResponse | null>(null)
  const [loadError, setLoadError] = useState('')
  const [isLoading, setLoading] = useState(false)
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [history, setHistory] = useState<string[]>([])
  const [cursor, setCursor] = useState(0)
  const panelRef = useRef<HTMLDivElement | null>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  // 焦点管理：打开时记住触发元素并把焦点移入面板；关闭时归还（无障碍惯例，非状态逻辑）
  useEffect(() => {
    if (!open) return
    previousFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    panelRef.current?.focus()
    return () => {
      previousFocusRef.current?.focus()
      previousFocusRef.current = null
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  // 打开时从 initialPath 加载（空串=驱动器列表）并重置导航历史；取消标记防卸载后 setState
  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoadError('')
    setLoading(true)
    setSelectedPath(null)
    setHistory([initialPath])
    setCursor(0)
    getBrowse(initialPath)
      .then((next) => {
        if (!cancelled) setListing(next)
      })
      .catch(() => {
        if (!cancelled) setLoadError('无法读取该文件夹，请重试')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, initialPath])

  /** 加载目录（loading/error 状态 + 失败保留旧视图）。 */
  function load(path: string): void {
    setLoading(true)
    setLoadError('')
    setSelectedPath(null)
    getBrowse(path)
      .then((next) => setListing(next))
      .catch(() => setLoadError('无法读取该文件夹，请重试'))
      .finally(() => setLoading(false))
  }

  /** 用户导航：截断前进栈后入栈并加载（历史栈驱动后退/前进可用性）。 */
  function navigateTo(path: string): void {
    const next = [...history.slice(0, cursor + 1), path]
    setHistory(next)
    setCursor(next.length - 1)
    load(path)
  }

  function goBack(): void {
    if (cursor <= 0) return
    const target = history[cursor - 1]
    if (target === undefined) return
    setCursor(cursor - 1)
    load(target)
  }

  function goForward(): void {
    if (cursor >= history.length - 1) return
    const target = history[cursor + 1]
    if (target === undefined) return
    setCursor(cursor + 1)
    load(target)
  }

  function goUp(): void {
    if (listing !== null && listing.parent !== null) navigateTo(listing.parent)
  }

  function handleEntryClick(entry: BrowseEntryPayload): void {
    setSelectedPath(entry.path)
    if (isCoarsePointer()) navigateTo(entry.path)
  }

  function handleEntryDoubleClick(entry: BrowseEntryPayload): void {
    navigateTo(entry.path)
  }

  if (!open) return null

  const canGoBack = cursor > 0 && !isLoading
  const canGoForward = cursor < history.length - 1 && !isLoading
  const canGoUp = listing !== null && listing.parent !== null && !isLoading
  const canConfirm = listing !== null && listing.path !== '' && !isLoading
  const segments = listing !== null ? breadcrumbSegments(listing.path) : ['此电脑']
  const entryCount = listing?.entries.length ?? 0

  return (
    <div className="folder-picker-overlay">
      <div
        className="folder-picker"
        role="dialog"
        aria-modal="true"
        aria-label="选择项目文件夹（本地）"
        ref={panelRef}
        tabIndex={-1}
      >
        <header className="folder-picker__header">
          <h2 className="folder-picker__title">选择项目文件夹（本地）</h2>
          <button
            type="button"
            className="folder-picker__close"
            aria-label="关闭"
            onClick={onClose}
          >
            ✕
          </button>
        </header>
        <div className="folder-picker__toolbar">
          <button
            type="button"
            className="folder-picker__nav"
            aria-label="后退"
            disabled={!canGoBack}
            onClick={goBack}
          >
            ←
          </button>
          <button
            type="button"
            className="folder-picker__nav"
            aria-label="前进"
            disabled={!canGoForward}
            onClick={goForward}
          >
            →
          </button>
          <button
            type="button"
            className="folder-picker__nav"
            aria-label="返回上级"
            disabled={!canGoUp}
            onClick={goUp}
          >
            ↑
          </button>
          <nav className="folder-picker__breadcrumb" aria-label="路径">
            {segments.map((segment, index) => {
              const isLast = index === segments.length - 1
              return (
                <span key={`${index}-${segment}`} className="folder-picker__crumb">
                  {isLast ? (
                    <span className="folder-picker__crumb-current" title={listing?.path ?? ''}>
                      {segment}
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="folder-picker__crumb-link"
                      onClick={() => navigateTo(segmentTarget(segments, index))}
                    >
                      {segment}
                    </button>
                  )}
                  {!isLast ? (
                    <span className="folder-picker__crumb-sep" aria-hidden="true">
                      ›
                    </span>
                  ) : null}
                </span>
              )
            })}
          </nav>
        </div>
        <div className="folder-picker__columns" aria-hidden="true">
          <span>名称</span>
          <span className="folder-picker__col-date">修改日期</span>
        </div>
        <div className="folder-picker__body">
          {loadError !== '' ? <p className="folder-picker__error">{loadError}</p> : null}
          {isLoading ? <p className="folder-picker__hint">加载中…</p> : null}
          {!isLoading && loadError === '' && listing !== null && entryCount === 0 ? (
            <p className="folder-picker__hint">此文件夹下没有子文件夹</p>
          ) : null}
          <ul className="folder-picker__list">
            {(listing?.entries ?? []).map((entry) => (
              <li key={entry.path}>
                <button
                  type="button"
                  aria-label={entry.name}
                  className={
                    selectedPath === entry.path
                      ? 'folder-picker__item folder-picker__item--selected'
                      : 'folder-picker__item'
                  }
                  onClick={() => handleEntryClick(entry)}
                  onDoubleClick={() => handleEntryDoubleClick(entry)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault()
                      navigateTo(entry.path)
                    }
                  }}
                >
                  <span className="folder-picker__item-label">
                    <FolderIcon />
                    <span className="folder-picker__item-name">{entry.name}</span>
                  </span>
                  <span className="folder-picker__item-date">
                    {formatDateTime(entry.modified_at)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {listing?.truncated ? (
            <p className="folder-picker__hint">目录过大，仅显示部分子文件夹</p>
          ) : null}
        </div>
        <footer className="folder-picker__footer">
          <span className="folder-picker__status">
            {listing !== null ? `${entryCount} 个文件夹` : ''}
          </span>
          <button type="button" className="folder-picker__cancel" onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className="folder-picker__confirm"
            disabled={!canConfirm}
            onClick={() => {
              if (listing !== null && listing.path !== '') onSelect(listing.path)
            }}
          >
            选择当前文件夹
          </button>
        </footer>
      </div>
    </div>
  )
}
