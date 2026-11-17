import type { ReactNode } from 'react'
import type { DemoPhase } from '../demoStream'
import type { LabCopy } from '../labCopy'
import { cx } from '../utils'

/** 三种流式呈现共用的外框：标题 / 说明 / 右上角三态（在跑 / 完成）。 */
export function StreamChrome({
  label,
  note,
  isPlaying,
  isFinished,
  elapsed,
  copy,
  children,
}: {
  label: string
  note: string
  isPlaying: boolean
  isFinished: boolean
  elapsed: string
  copy: LabCopy
  children: ReactNode
}) {
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-card border border-line bg-surface shadow-card">
      <header className="flex items-center gap-2 border-b border-line bg-code px-3 py-2">
        <span className="font-mono text-micro tracking-[0.14em] text-ink-2 uppercase">{label}</span>
        <span className="truncate text-micro text-ink-4">{note}</span>
        <span className="ml-auto inline-flex items-center gap-1.5 font-mono text-micro text-ink-3">
          <span
            aria-hidden="true"
            className={cx(
              'inline-block size-1.5 rounded-round',
              isPlaying ? 'bg-accent lab-dot--running' : isFinished ? 'bg-ok' : 'bg-ink-4',
            )}
          />
          {isPlaying ? copy.stream.running : isFinished ? copy.stream.done : '—'}
        </span>
        <span className="font-mono text-micro text-ink-4">{elapsed}</span>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2.5">{children}</div>
    </div>
  )
}

/** 空白态（回放未开始）：给一个就地可点的入口，避免三列空框看起来像坏了。 */
export function StreamEmpty({
  label,
  playLabel,
  onPlay,
}: {
  label: string
  playLabel: string
  onPlay: () => void
}) {
  return (
    <div className="flex min-h-[140px] flex-col items-center justify-center gap-2">
      <p className="text-micro text-ink-4">{label}</p>
      <button
        type="button"
        onClick={onPlay}
        className="inline-flex items-center gap-1.5 rounded-chip border border-line bg-canvas px-2.5 py-1 text-meta text-ink-2 hover:border-accent hover:text-ink"
      >
        <span aria-hidden="true">▶</span>
        {playLabel}
      </button>
    </div>
  )
}

/** 阶段小标签：当前阶段用强调色 + 左侧 2px 竖线，已完成只用弱色文字。 */
export function PhaseChip({
  phase,
  isCurrent,
  isDone,
  copy,
}: {
  phase: DemoPhase
  isCurrent: boolean
  isDone: boolean
  copy: LabCopy
}) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1.5 font-mono text-micro tracking-[0.12em] uppercase',
        isCurrent ? 'text-ink' : isDone ? 'text-ink-3' : 'text-ink-4',
      )}
    >
      <span
        aria-hidden="true"
        className={cx(
          'inline-block size-1.5 rounded-round',
          isCurrent ? 'bg-accent lab-dot--running' : isDone ? 'bg-ok' : 'bg-line-strong',
        )}
      />
      {copy.stream.phase[phase]}
    </span>
  )
}
