import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { ThinkingItem } from '../../schemas/stream'
import styles from './ChatStream.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

type ActionItem = Extract<ThinkingItem, { kind: 'action' }>

function ReadIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M3 4.5h4l1 1.6h5v6.4H3zM3 4.5V12"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function CommandIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <rect
        x="2.3"
        y="3"
        width="11.4"
        height="10"
        rx="2"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
      />
      <path
        d="M4.8 6.4 6.8 8l-2 1.6M8.4 9.6h2.6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function CopyIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
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

/** 耗时展示：<1s 用毫秒，≥1s 用一位小数秒；无值时不渲染（不显示占位破折号）。 */
export function formatDuration(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

/** 按条目类型分派（ChatStream 只负责分组，不关心具体渲染）。 */
export function TraceEntry({ item, index = 0 }: { item: ThinkingItem; index?: number }) {
  return item.kind === 'text' ? (
    <TraceThought text={item.text} />
  ) : (
    <TraceAction item={item} index={index} />
  )
}

/** 思考文字：本阶段正在写的那条由 TypewriterText 渲染，这里只兜底历史数据。 */
export function TraceThought({ text }: { text: string }) {
  return <p className={s('chat-reply__phase-text')}>{text}</p>
}

/**
 * 一条工具动作。两种形态自动选择：
 * - 读取文件 → 瘦胶囊行（路径已是主信息，不需要终端块）；
 * - 命令 → 终端块（`$` + 命令正文常显 + 右侧退出码胶囊 + 可展开输出）。
 * 两者都显示真实耗时与失败态；耗时缺失时整段不渲染。
 */
export function TraceAction({ item, index = 0 }: { item: ActionItem; index?: number }) {
  const { t } = useTranslation()
  const [isOpen, setOpen] = useState(false)
  const [isCopied, setCopied] = useState(false)
  // title 由后端下发（harness/trace.py 的动作名），后端按 locale 出同一文案，这里按当前语言的键比对。
  const isRead = item.title === t('trace.read_file')
  const isFailed = item.status === 'failed'
  // 失败时 scope 就是「Exit code N」：标题里直接带出退出码，折叠也能看出失败（对齐 CodeBuddy）
  const label = isRead
    ? t('trace.read_with_detail', { detail: item.detail })
    : isFailed
      ? t('trace.command_failed', { scope: item.scope })
      : t('trace.command_ok')
  const hasOutput = item.output !== ''
  const duration = item.durationMs
  // 执行中（2026-11-15 流式）：范围标签与耗时都还没到 → 卡片处于「正在产出」状态，
  // 对齐竞品的工具运行态（Trae/Claude Code 的 in_tool 标记）。
  const isStreaming = item.scope === '' && item.status !== 'failed'
  // 错峰延迟：同一阶段内的卡片依次浮现（上限 12 张，避免长列表末尾等待过久）
  const staggerMs = Math.min(index, 12) * 60

  function handleCopy(): void {
    void navigator.clipboard
      .writeText(item.detail)
      .then(() => setCopied(true))
      .catch(() => undefined)
  }

  return (
    <div
      className={s(
        isFailed
          ? 'trace-step trace-step--cmd trace-step--failed'
          : isRead
            ? 'trace-step'
            : 'trace-step trace-step--cmd',
      )}
      // 错峰入场（2026-11-15）：短命令的卡片几乎同时挂载，动画会一起播放 →
      // 递增延迟让它们「逐条浮现」，读起来是流式而不是整块弹出。
      style={staggerMs > 0 ? { animationDelay: `${staggerMs}ms` } : undefined}
    >
      <div className={s('trace-step__head')}>
        <button
          type="button"
          className={s('trace-step__toggle')}
          aria-expanded={isOpen}
          onClick={() => setOpen((open) => !open)}
        >
          <span className={s('trace-step__icon')} aria-hidden="true">
            {isRead ? <ReadIcon /> : <CommandIcon />}
          </span>
          <span className={s('trace-step__label')}>{label}</span>
          {isStreaming ? (
            <span className={s('trace-step__running')}>{t('trace.running')}</span>
          ) : null}
          {/* 失败命令的 scope 已经并进标题（「命令失败 · Exit code 1」），不再重复 */}
          {item.scope !== '' && !(isFailed && !isRead) ? (
            <span className={s('trace-step__scope')}>{item.scope}</span>
          ) : null}
          {duration !== undefined ? (
            <span className={s('trace-step__duration')}>{formatDuration(duration)}</span>
          ) : null}
          <span className={s('trace-step__caret')} aria-hidden="true">
            ›
          </span>
        </button>
        <button
          type="button"
          className={s('trace-step__copy')}
          aria-label={isCopied ? t('common.copied') : t('trace.copy_command')}
          onClick={handleCopy}
        >
          <CopyIcon />
        </button>
      </div>

      {/* 命令正文常显：终端块的信息主体就是这条命令，不该藏在折叠里 */}
      {!isRead ? (
        <div className={s('trace-step__cmd')}>
          <span className={s('trace-step__cmd-prompt')} aria-hidden="true">
            $
          </span>
          <code className={s('trace-step__cmd-text')}>{item.detail}</code>
          <span
            className={s(
              isFailed ? 'trace-step__exit trace-step__exit--failed' : 'trace-step__exit',
            )}
          >
            {isFailed ? 'exit 1' : 'exit 0'}
          </span>
        </div>
      ) : null}

      {isOpen ? (
        <div className={s('trace-step__body')}>
          {hasOutput ? (
            <pre className={s('trace-step__code trace-step__code--output')}>{item.output}</pre>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
