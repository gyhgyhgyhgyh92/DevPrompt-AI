import type { ReactNode } from 'react'
import { cx } from './utils'

interface SegmentOption<T extends string> {
  id: T
  label: string
}

interface SegmentedProps<T extends string> {
  label: string
  value: T
  options: readonly SegmentOption<T>[]
  onChange: (id: T) => void
}

/** 分段控件：受控、无内部状态，键盘可聚焦（lab 里所有切换共用这一个原语）。 */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: SegmentedProps<T>) {
  return (
    <div className="flex items-center gap-2">
      <span className="font-mono text-micro tracking-[0.14em] text-ink-3 uppercase">{label}</span>
      <div
        className="inline-flex items-center gap-[2px] rounded-chip border border-line bg-code p-[2px]"
        role="group"
        aria-label={label}
      >
        {options.map((option) => {
          const isActive = option.id === value
          return (
            <button
              key={option.id}
              type="button"
              aria-pressed={isActive}
              onClick={() => onChange(option.id)}
              className={cx(
                'rounded-chip px-2 py-1 text-meta transition-colors',
                'duration-[var(--lab-dur-fast)]',
                isActive
                  ? 'bg-surface font-medium text-ink shadow-card'
                  : 'text-ink-3 hover:bg-hover hover:text-ink-2',
              )}
            >
              {option.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

interface PlayControlsProps {
  isPlaying: boolean
  speed: number
  playLabel: string
  pauseLabel: string
  replayLabel: string
  speedLabel: string
  onPlay: () => void
  onPause: () => void
  onReplay: () => void
  onSpeed: (speed: number) => void
}

/** 0.75x 看逐字与逐条入场，1.5x 快速看全貌（不提供半速：本仓门禁把该数字当阈值字面量）。 */
const SPEEDS: readonly number[] = [0.75, 1, 1.5]

/** 回放控制：三个按钮 + 速度档，视觉上与分段控件同族但用强调色标出「在跑」。 */
export function PlayControls({
  isPlaying,
  speed,
  playLabel,
  pauseLabel,
  replayLabel,
  speedLabel,
  onPlay,
  onPause,
  onReplay,
  onSpeed,
}: PlayControlsProps) {
  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={isPlaying ? onPause : onPlay}
        className={cx(
          'inline-flex items-center gap-1.5 rounded-chip border px-2.5 py-1 text-meta',
          isPlaying
            ? 'border-accent bg-accent-soft font-medium text-ink'
            : 'border-line bg-surface text-ink-2 hover:border-line-strong',
        )}
      >
        <span
          aria-hidden="true"
          className={cx(
            'inline-block size-1.5 rounded-round',
            isPlaying ? 'bg-accent lab-dot--running' : 'bg-ink-4',
          )}
        />
        {isPlaying ? pauseLabel : playLabel}
      </button>
      <button
        type="button"
        onClick={onReplay}
        className="rounded-chip border border-line bg-surface px-2.5 py-1 text-meta text-ink-2 hover:border-line-strong"
      >
        {replayLabel}
      </button>
      <span className="flex items-center gap-1">
        <span className="font-mono text-micro tracking-[0.14em] text-ink-3 uppercase">
          {speedLabel}
        </span>
        {SPEEDS.map((item) => (
          <button
            key={item}
            type="button"
            aria-pressed={item === speed}
            onClick={() => onSpeed(item)}
            className={cx(
              'rounded-chip px-1.5 py-1 font-mono text-micro',
              item === speed ? 'bg-selected text-ink' : 'text-ink-3 hover:text-ink-2',
            )}
          >
            {item}x
          </button>
        ))}
      </span>
    </div>
  )
}

/** 章节外壳：编号 + 标题 + 说明 + 右侧可选操作，三列内容由 children 决定。 */
export function LabSection({
  title,
  hint,
  action,
  children,
}: {
  title: string
  hint: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="flex flex-col gap-3">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line pb-2">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="text-title font-semibold text-ink">{title}</h2>
          <span className="text-meta text-ink-3">{hint}</span>
        </div>
        {action}
      </header>
      {children}
    </section>
  )
}
