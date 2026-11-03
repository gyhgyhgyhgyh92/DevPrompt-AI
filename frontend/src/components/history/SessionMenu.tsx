import { useEffect, useRef } from 'react'
import './SessionMenu.css'

interface SessionMenuProps {
  /** 当前条目是否已置顶（决定「置顶任务」项语义）。 */
  isPinned: boolean
  onPin: () => void
  onCopyPath: () => void
  onRename: () => void
  onDelete: () => void
  /** Esc / 外点关闭时回调（父组件清除 openMenuId）。 */
  onClose: () => void
}

function PinIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M8 1.5 9.6 5l3.4.4-2.5 2.3.7 3.4L8 9.4l-3.2 1.7.7-3.4L3 5.4 6.4 5 8 1.5Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
      <path d="M8 9.4V14" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  )
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

function PencilIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M11.5 2.5 13.5 4.5 5 13H3v-2l8.5-8.5Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function TrashIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
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

/**
 * 条目 ⋮ 弹出菜单（图四 1:1，spec Task 5，F-703）：4 项（置顶任务/复制项目路径/重命名/删除任务）。
 * Esc 与外点关闭；Tab 可达（原生 button）；删除为红色，点击后上抛给外层统一确认弹窗
 * （2026-11-01：原菜单内「二次点击」改为 `ConfirmDialog`，与项目级删除同一套确认形态）。
 */
export function SessionMenu({
  isPinned,
  onPin,
  onCopyPath,
  onRename,
  onDelete,
  onClose,
}: SessionMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handlePointerDown(event: MouseEvent): void {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        onClose()
      }
    }
    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [onClose])

  return (
    <div className="session-menu" role="menu" ref={menuRef} aria-label="会话操作">
      <button
        type="button"
        role="menuitem"
        className="session-menu__item"
        aria-pressed={isPinned}
        onClick={onPin}
      >
        <PinIcon />
        <span>置顶任务</span>
      </button>
      <button type="button" role="menuitem" className="session-menu__item" onClick={onCopyPath}>
        <FolderIcon />
        <span>复制项目路径</span>
      </button>
      <button type="button" role="menuitem" className="session-menu__item" onClick={onRename}>
        <PencilIcon />
        <span>重命名</span>
      </button>
      <button
        type="button"
        role="menuitem"
        className="session-menu__item session-menu__item--danger"
        onClick={onDelete}
      >
        <TrashIcon />
        <span>删除任务</span>
      </button>
    </div>
  )
}
