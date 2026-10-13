import { useEffect, useRef, useState } from 'react'
import { getBrowse } from '../../api/endpoints'
import type { BrowseResponse } from '../../api/types'
import './FolderPickerModal.css'

export interface FolderPickerModalProps {
  open: boolean
  /** 打开时优先浏览的目录（通常为已选项目路径；空串则从驱动器列表开始）。 */
  initialPath: string
  onSelect: (path: string) => void
  onClose: () => void
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
 * 页内文件夹选择器（F-601「选择文件夹（本地）」）：完全嵌入浏览器页面（DOM 模态，
 * 属于页面视口、随页面滚动呈现），不弹系统桌面窗口。浏览器沙箱禁读本地绝对路径，
 * 目录列表由后端 GET /project/browse 提供（path 空串=驱动器列表）。
 * 交互与设置模态对齐：Esc/✕ 关闭、焦点入面板并归还；确认返回当前所在目录。
 */
export function FolderPickerModal(props: FolderPickerModalProps) {
  const { open, initialPath, onSelect, onClose } = props
  const [listing, setListing] = useState<BrowseResponse | null>(null)
  const [loadError, setLoadError] = useState('')
  const [isLoading, setLoading] = useState(false)
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

  // 打开时从 initialPath 加载（空串=驱动器列表）；取消标记防卸载后 setState
  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoadError('')
    setLoading(true)
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

  /** 交互导航（进入子目录 / 返回上级）：失败保留当前视图并展示错误。 */
  function navigate(path: string): void {
    setLoading(true)
    setLoadError('')
    getBrowse(path)
      .then((next) => setListing(next))
      .catch(() => setLoadError('无法读取该文件夹，请重试'))
      .finally(() => setLoading(false))
  }

  if (!open) return null

  const canGoUp = listing !== null && listing.parent !== null && !isLoading
  const canConfirm = listing !== null && listing.path !== '' && !isLoading
  const displayPath = listing !== null && listing.path !== '' ? listing.path : '此电脑'

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
        <div className="folder-picker__pathbar">
          <button
            type="button"
            className="folder-picker__up"
            aria-label="返回上级"
            disabled={!canGoUp}
            onClick={() => {
              if (listing !== null && listing.parent !== null) navigate(listing.parent)
            }}
          >
            ← 返回上级
          </button>
          <span className="folder-picker__path" title={displayPath}>
            {displayPath}
          </span>
        </div>
        <div className="folder-picker__body">
          {loadError !== '' ? <p className="folder-picker__error">{loadError}</p> : null}
          {isLoading ? <p className="folder-picker__hint">加载中…</p> : null}
          {!isLoading && loadError === '' && listing !== null && listing.entries.length === 0 ? (
            <p className="folder-picker__hint">此位置没有子文件夹</p>
          ) : null}
          <ul className="folder-picker__list">
            {(listing?.entries ?? []).map((entry) => (
              <li key={entry.path}>
                <button
                  type="button"
                  className="folder-picker__item"
                  onClick={() => navigate(entry.path)}
                >
                  <FolderIcon />
                  <span className="folder-picker__item-name">{entry.name}</span>
                </button>
              </li>
            ))}
          </ul>
          {listing?.truncated ? (
            <p className="folder-picker__hint">目录过大，仅显示部分子文件夹</p>
          ) : null}
        </div>
        <footer className="folder-picker__footer">
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
