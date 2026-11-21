import { useEffect, useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown } from 'lucide-react'

interface AskPanelProps {
  /** 本轮问题总数。 */
  total: number
  /** 已回答的问题数（头部计数）。 */
  answered: number
  /** 提交中：禁用按钮、忽略 Esc。 */
  isBusy: boolean
  /** 自定义标题（软护栏态用）；缺省为「需要你确认 N 个问题」。 */
  title?: string
  onSubmit: () => void
  /** Esc / 「直接生成」：沿用既有逃生语义（MUST-26）。 */
  onEscape: () => void
  children: React.ReactNode
}

/**
 * 反问面板（2026-10-20 v2）：**嵌在对话流里**，不弹层、不遮罩。
 *
 * 高度自适应：内容少时卡片随内容变矮；超过 `min(60vh, 680px)` 后只有中部滚动，
 * 头尾始终可见。之前一版是 Portal 弹窗，用户实测后要求回到聊天流内。
 */
export function AskPanel({
  total,
  answered,
  isBusy,
  title,
  onSubmit,
  onEscape,
  children,
}: AskPanelProps) {
  const { t } = useTranslation()
  const bodyId = useId()
  // 折叠为纯表现层局部状态（MUST-16 不上提）；新一批问题由父级 key 重挂载回到展开态
  const [isCollapsed, setCollapsed] = useState(false)
  const heading = title ?? `需要你确认 ${total} 个问题`

  // Esc = 直接生成；提交中与收起态不响应（收起时按键不可见，响应等于误触逃生）
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key !== 'Escape' || isBusy || isCollapsed) return
      event.preventDefault()
      onEscape()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isBusy, isCollapsed, onEscape])

  return (
    <section className="ask-panel" role="group" aria-label={heading}>
      <header className="ask-panel__head">
        <button
          type="button"
          className="ask-panel__toggle"
          aria-expanded={!isCollapsed}
          aria-controls={isCollapsed ? undefined : bodyId}
          onClick={() => setCollapsed((current) => !current)}
        >
          <span className="ask-panel__icon" aria-hidden="true">
            ?
          </span>
          <span className="ask-panel__title">{heading}</span>
          <span className="ask-panel__progress">
            {answered} / {total} 已答
          </span>
          <span className="ask-panel__caret" aria-hidden="true">
            <ChevronDown size={14} strokeWidth={1.5} />
          </span>
        </button>
      </header>

      {isCollapsed ? null : (
        <>
          <div className="ask-panel__body" id={bodyId}>
            {children}
          </div>

          <footer className="ask-panel__foot">
            <span className="ask-panel__hint">{t('clarify.esc_hint')}</span>
            <div className="ask-panel__actions">
              <button
                type="button"
                className="button button--ghost"
                disabled={isBusy}
                onClick={onEscape}
              >
                {t('clarify.generate_direct')}
              </button>
              <button
                type="button"
                className="button button--primary"
                disabled={isBusy}
                onClick={onSubmit}
              >
                {t('clarify.submit')}
              </button>
            </div>
          </footer>
        </>
      )}
    </section>
  )
}
