import { useEffect } from 'react'

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
  // Esc = 直接生成；提交中不响应，避免并发请求
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key !== 'Escape' || isBusy) return
      event.preventDefault()
      onEscape()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isBusy, onEscape])

  return (
    <section className="ask-panel" role="group" aria-label={title ?? `需要你确认 ${total} 个问题`}>
      <header className="ask-panel__head">
        <span className="ask-panel__icon" aria-hidden="true">
          ?
        </span>
        <h2 className="ask-panel__title">{title ?? `需要你确认 ${total} 个问题`}</h2>
        <span className="ask-panel__progress">
          {answered} / {total} 已答
        </span>
      </header>

      <div className="ask-panel__body">{children}</div>

      <footer className="ask-panel__foot">
        <span className="ask-panel__hint">Esc 取消 · 有多选时可勾多项</span>
        <div className="ask-panel__actions">
          <button
            type="button"
            className="button button--ghost"
            disabled={isBusy}
            onClick={onEscape}
          >
            直接生成
          </button>
          <button
            type="button"
            className="button button--primary"
            disabled={isBusy}
            onClick={onSubmit}
          >
            提交
          </button>
        </div>
      </footer>
    </section>
  )
}
