import type { ThinkingItem } from '../../schemas/stream'
import { makeS } from '../../utils/css'
import styles from './ChatStream.module.css'
import { TraceEntry } from './TraceEntry'
import { TypewriterText } from './TypewriterText'

const s = makeS(styles)

export interface PhaseRow {
  phase: string
  /** 阶段名（已本地化，来自 chat.phase.*.label）。 */
  label: string
  /** 这一步在做什么（已本地化）。 */
  hint: string
  /** 右端等宽元信息：动作计数（无动作时为空串）。 */
  meta: string
  /** 当前阶段的运行标记；已完成/未开始为 null。 */
  tag: string | null
  isCurrent: boolean
  isDone: boolean
  logs: readonly ThinkingItem[]
}

function DoneGlyph() {
  return (
    <svg width="11" height="11" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M3.6 8.4l2.8 2.8 6-6.4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function PendingGlyph() {
  return (
    <svg width="11" height="11" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <circle cx="8" cy="8" r="3.2" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  )
}

function RunningGlyph() {
  return (
    <svg width="11" height="11" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <circle cx="8" cy="8" r="3.6" fill="currentColor" />
    </svg>
  )
}

interface PhaseLedgerProps {
  rows: readonly PhaseRow[]
  /** 正在逐字呈现的那条思考的 id（其余条目直接整段显示）。 */
  animatingId: string | null
}

/**
 * 执行账本（替代原来的「✓ ● ○」进度列表）：每阶段一行——
 * 状态字形 + 等宽大写阶段名 + 这一步在做什么 + 右端动作计数。
 * 失败不会出现在阶段层（阶段本身没有失败态），失败由工具卡承担。
 */
export function PhaseLedger({ rows, animatingId }: PhaseLedgerProps) {
  return (
    <ol className={s('chat-reply__phases')}>
      {rows.map((row) => {
        const stateClass = row.isCurrent
          ? 'chat-reply__phase chat-reply__phase--current'
          : row.isDone
            ? 'chat-reply__phase chat-reply__phase--done'
            : 'chat-reply__phase'
        return (
          <li
            key={row.phase}
            className={s(stateClass)}
            aria-current={row.isCurrent ? 'step' : undefined}
          >
            <div className={s('chat-reply__phase-head')}>
              <span
                className={s(
                  'chat-reply__phase-mark',
                  row.isCurrent
                    ? 'chat-reply__phase-mark--running'
                    : row.isDone
                      ? 'chat-reply__phase-mark--done'
                      : '',
                )}
                aria-hidden="true"
              >
                {row.isCurrent ? <RunningGlyph /> : row.isDone ? <DoneGlyph /> : <PendingGlyph />}
              </span>
              <span className={s('chat-reply__phase-label')}>{row.label}</span>
              <span className={s('chat-reply__phase-hint')}>{row.hint}</span>
              {row.meta !== '' ? (
                <span className={s('chat-reply__phase-meta')}>{row.meta}</span>
              ) : null}
              {row.tag !== null ? (
                <span className={s('chat-reply__phase-tag')}>{row.tag}</span>
              ) : null}
            </div>
            {row.logs.length > 0 ? (
              <div className={s('chat-reply__phase-log')}>
                {row.logs.map((item, index) =>
                  item.kind === 'text' ? (
                    <TypewriterText
                      key={item.id}
                      className={s('chat-reply__phase-text')}
                      text={item.text}
                      isAnimating={item.id === animatingId}
                    />
                  ) : (
                    <TraceEntry key={item.id} item={item} index={index} />
                  ),
                )}
              </div>
            ) : null}
          </li>
        )
      })}
    </ol>
  )
}
