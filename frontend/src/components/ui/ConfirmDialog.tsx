import { useEffect, useId, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useFocusTrap } from '../../hooks/useFocusTrap'
import styles from './ConfirmDialog.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

export interface ConfirmDialogProps {
  /** 弹窗标题（如「删除项目」）。 */
  title: string
  /** 正文：必须写清后果与不可逆项（如「不会删除本地文件」）。 */
  description: string
  /** 确认按钮文案（如「删除」）。 */
  confirmLabel: string
  /** 提交中：禁用按钮并忽略 Esc / 遮罩点击（有副作用端点禁重试，MUST-15）。 */
  isBusy: boolean
  onConfirm: () => void
  onClose: () => void
}

/**
 * 通用确认对话框（2026-11-01）：遮罩 + 标题 + 正文 + 取消/确认。
 *
 * 纯展示组件，不调 API、不持有业务状态；打开时焦点入面板、关闭归还触发元素
 * （沿用 `SettingsModal` 的焦点手法）。危险动作由调用方给 `confirmLabel` 文案，
 * 组件不判断「该不该删」——那是业务判定（MUST-08）。
 */
export function ConfirmDialog({
  title,
  description,
  confirmLabel,
  isBusy,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  const { t } = useTranslation()
  const panelRef = useRef<HTMLDivElement | null>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)
  const titleId = useId()

  useEffect(() => {
    previousFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    panelRef.current?.focus()
    return () => {
      previousFocusRef.current?.focus()
      previousFocusRef.current = null
    }
  }, [])

  // Esc = 取消；提交中不响应（请求已发出，关掉只剩半成品）
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key !== 'Escape' || isBusy) return
      event.preventDefault()
      onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isBusy, onClose])

  // 焦点陷阱：Tab 在对话框内循环，不逃逸到背景
  useFocusTrap(panelRef, true)

  return (
    <div
      className={s('confirm-overlay')}
      onClick={(event) => {
        if (event.target === event.currentTarget && !isBusy) onClose()
      }}
    >
      <div
        className={s('confirm-dialog')}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={panelRef}
        tabIndex={-1}
      >
        <h2 className={s('confirm-dialog__title')} id={titleId}>
          {title}
        </h2>
        <p className={s('confirm-dialog__desc')}>{description}</p>
        <div className={s('confirm-dialog__actions')}>
          <button
            type="button"
            className={s('button button--ghost')}
            disabled={isBusy}
            onClick={onClose}
          >
            {t('common.cancel')}
          </button>
          <button
            type="button"
            className={s('confirm-dialog__confirm')}
            disabled={isBusy}
            onClick={onConfirm}
          >
            {isBusy ? t('common.processing') : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
