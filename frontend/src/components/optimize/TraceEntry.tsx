import { useState } from 'react'
import type { ThinkingItem } from '../../schemas/stream'
import './optimize.css'

type ActionItem = Extract<ThinkingItem, { kind: 'action' }>

function ReadIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M3 5.5l3.5 2.5L3 10.5M8 5.5L11.5 8 8 10.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function CommandIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <rect
        x="2.5"
        y="3"
        width="11"
        height="10"
        rx="2"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
      />
      <path d="M5 6.5h6M5 9.5h4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  )
}

function CopyIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M5.5 5.5h7v7h-7zM3.5 10.5v-7h7"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/** 按条目类型分派（ChatStream 只负责分组，不关心具体渲染）。 */
export function TraceEntry({ item }: { item: ThinkingItem }) {
  return item.kind === 'text' ? <TraceThought text={item.text} /> : <TraceAction item={item} />
}

/** 思考文字：灰底圆角块（2026-10-22，对齐参考截图的「思考块」）。 */
export function TraceThought({ text }: { text: string }) {
  return <p className="trace-thought">{text}</p>
}

/**
 * 一个工具动作：一行标题（图标 + 「已读取 X」/「命令已执行」+ 复制 + 展开箭头），
 * 展开后是灰底代码块（命令 + 输出）。折叠状态留在组件内（MUST-16）。
 */
export function TraceAction({ item }: { item: ActionItem }) {
  const [isOpen, setOpen] = useState(false)
  const [isCopied, setCopied] = useState(false)
  const isRead = item.title === '读取文件'
  const isFailed = item.status === 'failed'
  // 失败时 scope 就是「Exit code N」：标题里直接带出退出码，折叠也能看出失败（对齐 CodeBuddy）
  const label = isRead
    ? `已读取 ${item.detail}`
    : isFailed
      ? `命令失败 · ${item.scope}`
      : '命令已执行'
  const command = isRead ? '' : item.detail
  const hasBody = command !== '' || item.output !== ''

  function handleCopy(): void {
    void navigator.clipboard
      .writeText(item.detail)
      .then(() => setCopied(true))
      .catch(() => undefined)
  }

  return (
    <div className={isFailed ? 'trace-step trace-step--failed' : 'trace-step'}>
      <div className="trace-step__head">
        <button
          type="button"
          className="trace-step__toggle"
          aria-expanded={isOpen}
          disabled={!hasBody}
          onClick={() => setOpen((open) => !open)}
        >
          <span className="trace-step__icon" aria-hidden="true">
            {isRead ? <ReadIcon /> : <CommandIcon />}
          </span>
          <span className="trace-step__label">{label}</span>
          {item.scope !== '' ? <span className="trace-step__scope">{item.scope}</span> : null}
          {hasBody ? (
            <span className="trace-step__caret" aria-hidden="true">
              ›
            </span>
          ) : null}
        </button>
        <button
          type="button"
          className="trace-step__copy"
          aria-label={isCopied ? '已复制' : '复制命令'}
          onClick={handleCopy}
        >
          <CopyIcon />
        </button>
      </div>

      {isOpen ? (
        <div className="trace-step__body">
          {command !== '' ? <pre className="trace-step__code">{command}</pre> : null}
          {item.output !== '' ? (
            <pre className="trace-step__code trace-step__code--output">{item.output}</pre>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
