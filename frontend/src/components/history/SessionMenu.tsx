import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Folder, Pencil, Pin, Trash2 } from 'lucide-react'
import styles from './SessionMenu.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

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
  return <Pin size={16} strokeWidth={1.5} aria-hidden="true" />
}

function FolderIcon() {
  return <Folder size={16} strokeWidth={1.5} aria-hidden="true" />
}

function PencilIcon() {
  return <Pencil size={16} strokeWidth={1.5} aria-hidden="true" />
}

function TrashIcon() {
  return <Trash2 size={16} strokeWidth={1.5} aria-hidden="true" />
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
  const { t } = useTranslation()
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
    <div
      className={s('session-menu')}
      role="menu"
      ref={menuRef}
      aria-label={t('history.menu_label')}
    >
      <button
        type="button"
        role="menuitem"
        className={s('session-menu__item')}
        aria-pressed={isPinned}
        onClick={onPin}
      >
        <PinIcon />
        <span>{t('history.menu_pin')}</span>
      </button>
      <button
        type="button"
        role="menuitem"
        className={s('session-menu__item')}
        onClick={onCopyPath}
      >
        <FolderIcon />
        <span>{t('history.menu_copy_path')}</span>
      </button>
      <button type="button" role="menuitem" className={s('session-menu__item')} onClick={onRename}>
        <PencilIcon />
        <span>{t('history.menu_rename')}</span>
      </button>
      <button
        type="button"
        role="menuitem"
        className={s('session-menu__item session-menu__item--danger')}
        onClick={onDelete}
      >
        <TrashIcon />
        <span>{t('history.menu_delete')}</span>
      </button>
    </div>
  )
}
