/**
 * 历史轮过程区（2026-11-15）：默认折叠成一行摘要，点开回看。
 *
 * 有两套数据源：
 * - `thinking`：后端从 run_events 重建的完整过程（thought + action，action 带工具 output），
 *   与当前轮同构，直接用 PhaseLedger 渲染，动作卡片自带展开；
 * - `steps`：旧轮只有落库的动作摘要（无 output），退化为可折叠步骤列表，单步可看 note。
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { ThinkingItem } from '../../schemas/stream'
import { PhaseLedger } from './PhaseLedger'
import { formatDuration } from './TraceEntry'
import { buildPhaseRows } from './turnThinking'
import styles from './ChatStream.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

interface TurnProcessProps {
  thinking?: readonly ThinkingItem[]
  steps?: readonly Record<string, unknown>[]
}

function stepLabel(step: Record<string, unknown>): string {
  return typeof step.action === 'string' ? step.action : ''
}

function stepNote(step: Record<string, unknown>): string {
  return typeof step.note === 'string' ? step.note : ''
}

function stepDuration(step: Record<string, unknown>): number | undefined {
  return typeof step.duration_ms === 'number' ? step.duration_ms : undefined
}

export function TurnProcess({ thinking, steps }: TurnProcessProps) {
  const { t } = useTranslation()
  const [isOpen, setOpen] = useState(false)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const items = thinking ?? []
  const stepList = steps ?? []
  const hasTimeline = items.length > 0
  if (!hasTimeline && stepList.length === 0) return null

  const actionCount = hasTimeline
    ? items.filter((item) => item.kind === 'action').length
    : stepList.length
  const rows = hasTimeline
    ? buildPhaseRows({
        thinking: items,
        state: 'DONE',
        translate: t,
        isLive: false,
        hadAsk: items.some((item) => item.phase === 'ASKING'),
      })
    : []

  function toggleStep(index: number): void {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  return (
    <div className={s('turn-process')}>
      <button
        type="button"
        className={s('chat-reply__process-toggle')}
        aria-expanded={isOpen}
        onClick={() => setOpen((open) => !open)}
      >
        <span>
          {t(hasTimeline ? 'chat.turn_process' : 'chat.turn_steps', { count: actionCount })}
        </span>
        <span className={s('chat-reply__process-caret')} aria-hidden="true">
          {isOpen ? '▾' : '▸'}
        </span>
      </button>

      {isOpen ? (
        hasTimeline ? (
          <PhaseLedger rows={rows} animatingId={null} />
        ) : (
          <ol className={s('turn-steps')}>
            {stepList.map((step, index) => {
              const note = stepNote(step)
              const duration = stepDuration(step)
              const failed = step.outcome === 'failed'
              const isExpanded = expanded.has(index)
              return (
                <li
                  key={`step-${index}`}
                  className={s(
                    failed ? 'turn-steps__row turn-steps__row--failed' : 'turn-steps__row',
                  )}
                >
                  <button
                    type="button"
                    className={s('turn-steps__head')}
                    aria-expanded={isExpanded}
                    onClick={() => toggleStep(index)}
                  >
                    <span className={s('turn-steps__action')}>{stepLabel(step)}</span>
                    {duration !== undefined ? (
                      <span className={s('turn-steps__duration')}>{formatDuration(duration)}</span>
                    ) : null}
                    <span className={s('turn-steps__caret')} aria-hidden="true">
                      ›
                    </span>
                  </button>
                  {isExpanded ? (
                    <p className={s('turn-steps__note')}>
                      {note !== '' ? note : t('chat.step_none')}
                    </p>
                  ) : null}
                </li>
              )
            })}
          </ol>
        )
      ) : null}
    </div>
  )
}
