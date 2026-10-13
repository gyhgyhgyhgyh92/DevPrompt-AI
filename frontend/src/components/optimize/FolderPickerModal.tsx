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

/** 搜索防抖（实时输入响应，避免逐键递归扫描；决策 10）。 */
const SEARCH_DEBOUNCE_MS = 250

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

/** 搜索图标（图二，自绘 SVG，MUST-04）：放大镜（圆 + 手柄）。 */
function SearchIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <circle cx="7" cy="7" r="4.2" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M10.2 10.2 13.5 13.5" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  )
}

/**
 * 页内文件夹选择器（F-601「选择文件夹（本地）」，Win11 风格复刻）：完全嵌入浏览器页面
 * （DOM 模态，属于页面视口），不弹系统桌面窗口。浏览器沙箱禁读本地绝对路径，目录条目
 * （名称 + 修改日期；仅目录，文件不出现——用户裁定）由后端 GET /project/browse 提供。
 * 排序（名称升序）由后端固定。
 * 交互：后退/前进/上级 + 地址栏面包屑跳转；单击选中（触屏单击即进入）、双击进入；
 * Esc/✕ 关闭、焦点入面板并归还；确认返回当前所在目录。
 * 搜索（图二，2026-10-13 新增，参考 Win11 资源管理器）：地址栏同行右侧搜索框，250ms 防抖
 * 实时响应；命中当前文件夹**子树**（含子目录递归，后端 `q` 参数），结果附相对路径提示；
 * 范围控制——驱动器列表态禁用；导航即退出搜索；Esc 清空查询（不关闭模态）。
 */
export function FolderPickerModal(props: FolderPickerModalProps) {
  const { open, initialPath, onSelect, onClose } = props
  const [listing, setListing] = useState<BrowseResponse | null>(null)
  const [loadError, setLoadError] = useState('')
  const [isLoading, setLoading] = useState(false)
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [history, setHistory] = useState<string[]>([])
  const [cursor, setCursor] = useState(0)
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  // 基准目录（搜索范围）：导航时更新；搜索响应 `path` 仍返回基准目录，范围不漂移（决策 8）
  const basePathRef = useRef('')
  // 是否处于搜索态：用于「归空时恢复普通列表」且避免 open 时重复加载
  const isSearchActiveRef = useRef(false)
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

  // 打开时从 initialPath 加载（空串=驱动器列表）并重置导航历史与搜索；取消标记防卸载后 setState
  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoadError('')
    setLoading(true)
    setSelectedPath(null)
    setHistory([initialPath])
    setCursor(0)
    basePathRef.current = initialPath
    isSearchActiveRef.current = false
    setQuery('')
    setDebouncedQuery('')
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

  // 防抖：输入即响应，250ms 后落到 debouncedQuery；清空立即生效（不等待防抖）
  useEffect(() => {
    if (!open) return
    if (query === '') {
      setDebouncedQuery('')
      return
    }
    const timer = setTimeout(() => setDebouncedQuery(query), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [open, query])

  // 搜索加载：debouncedQuery 非空 → 以基准目录递归搜索；归空 → 恢复基准目录普通列表
  useEffect(() => {
    if (!open) return
    const trimmed = debouncedQuery.trim()
    const base = basePathRef.current
    if (trimmed !== '') {
      if (base === '') return
      isSearchActiveRef.current = true
      load(base, trimmed)
      return
    }
    if (isSearchActiveRef.current) {
      isSearchActiveRef.current = false
      if (base !== '') load(base)
    }
  }, [open, debouncedQuery])

  /** 加载目录（loading/error 状态 + 失败保留旧视图）；query 非空为子树递归搜索。 */
  function load(path: string, searchQuery = ''): void {
    setLoading(true)
    setLoadError('')
    setSelectedPath(null)
    getBrowse(path, searchQuery)
      .then((next) => setListing(next))
      .catch(() => setLoadError('无法读取该文件夹，请重试'))
      .finally(() => setLoading(false))
  }

  /** 退出搜索：清空查询并立即归零防抖值（避免与导航加载重复请求）。 */
  function exitSearch(): void {
    isSearchActiveRef.current = false
    setQuery('')
    setDebouncedQuery('')
  }

  /** 用户导航：截断前进栈后入栈并加载；同时退出搜索并更新基准目录。 */
  function navigateTo(path: string): void {
    exitSearch()
    basePathRef.current = path
    const next = [...history.slice(0, cursor + 1), path]
    setHistory(next)
    setCursor(next.length - 1)
    load(path)
  }

  function goBack(): void {
    if (cursor <= 0) return
    const target = history[cursor - 1]
    if (target === undefined) return
    exitSearch()
    basePathRef.current = target
    setCursor(cursor - 1)
    load(target)
  }

  function goForward(): void {
    if (cursor >= history.length - 1) return
    const target = history[cursor + 1]
    if (target === undefined) return
    exitSearch()
    basePathRef.current = target
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
  const isSearchMode = debouncedQuery.trim() !== ''
  const entryCount = listing?.entries.length ?? 0
  const canSearch = listing !== null && listing.path !== ''

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
          <div className="folder-picker__search">
            <SearchIcon />
            <input
              className="folder-picker__search-input"
              aria-label="搜索当前文件夹"
              placeholder="搜索"
              value={query}
              disabled={!canSearch}
              onChange={(event) => setQuery(event.currentTarget.value)}
              onKeyDown={(event) => {
                if (event.key === 'Escape') {
                  event.stopPropagation()
                  setQuery('')
                }
              }}
            />
            {query !== '' ? (
              <button
                type="button"
                className="folder-picker__search-clear"
                aria-label="清除搜索"
                onClick={() => setQuery('')}
              >
                ✕
              </button>
            ) : null}
          </div>
        </div>
        <div className="folder-picker__columns" aria-hidden="true">
          <span>名称</span>
          <span className="folder-picker__col-date">修改日期</span>
        </div>
        <div className="folder-picker__body">
          {loadError !== '' ? <p className="folder-picker__error">{loadError}</p> : null}
          {isLoading ? <p className="folder-picker__hint">加载中…</p> : null}
          {!isLoading && loadError === '' && listing !== null && entryCount === 0 ? (
            <p className="folder-picker__hint">
              {isSearchMode ? '未找到匹配的文件夹' : '此文件夹下没有子文件夹'}
            </p>
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
                    {entry.rel_parent ? (
                      <span className="folder-picker__item-rel">{entry.rel_parent}</span>
                    ) : null}
                  </span>
                  <span className="folder-picker__item-date">
                    {formatDateTime(entry.modified_at)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {listing?.truncated ? (
            <p className="folder-picker__hint">
              {isSearchMode ? '结果过多，仅显示前 500 项' : '目录过大，仅显示部分子文件夹'}
            </p>
          ) : null}
        </div>
        <footer className="folder-picker__footer">
          <span className="folder-picker__status">
            {listing !== null
              ? isSearchMode
                ? `${entryCount} 个搜索结果`
                : `${entryCount} 个文件夹`
              : ''}
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
