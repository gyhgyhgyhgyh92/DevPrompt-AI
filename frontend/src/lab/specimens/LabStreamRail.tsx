import { motion } from 'motion/react'
import { type DemoView, elapsedAt, groupDemoByPhase } from '../demoStream'
import type { LabCopy } from '../labCopy'
import { PhaseChip, StreamChrome, StreamEmpty } from './LabStreamShared'
import { LabToolCard } from './LabToolCard'

interface LabStreamRailProps {
  view: DemoView
  copy: LabCopy
  applied: number
  isPlaying: boolean
  isReduced: boolean
  onPlay: () => void
}

/**
 * V2 阶段轨道：执行日志式排版。
 * 左轨表示「任务一直在推进」，每步一行状态词，动作折叠成带耗时的胶囊；失败留在原位不隐藏。
 */
export function LabStreamRail({
  view,
  copy,
  applied,
  isPlaying,
  isReduced,
  onPlay,
}: LabStreamRailProps) {
  const groups = groupDemoByPhase(view)

  return (
    <StreamChrome
      label={copy.variants.rail.name}
      note={copy.variants.rail.note}
      isPlaying={isPlaying}
      isFinished={view.isFinished}
      elapsed={elapsedAt(applied)}
      copy={copy}
    >
      {applied === 0 ? (
        <StreamEmpty label={copy.stream.empty} playLabel={copy.controls.play} onPlay={onPlay} />
      ) : null}
      <div className="relative flex flex-col gap-3 pl-4">
        <span aria-hidden="true" className="absolute inset-y-0 left-[3px] w-px bg-line" />
        {groups.map((group, index) => {
          const isCurrent = group.phase === view.phase && !view.isFinished
          const isDone = index < groups.length - 1 || view.isFinished
          return (
            <motion.section
              key={group.phase}
              initial={isReduced ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.24, ease: [0.2, 0.7, 0.3, 1] }}
              className="relative"
            >
              <span
                aria-hidden="true"
                className={
                  isCurrent
                    ? 'lab-rail-flow absolute -left-4 top-0 h-full w-[2px] rounded-round'
                    : 'absolute -left-4 top-1.5 size-1.5 rounded-round bg-line-strong'
                }
              />
              <header className="flex items-center gap-2 py-[2px]">
                <PhaseChip phase={group.phase} isCurrent={isCurrent} isDone={isDone} copy={copy} />
                <span className="ml-auto font-mono text-micro text-ink-4">
                  {group.actions.length} {copy.stream.actions}
                </span>
              </header>
              <div className="mt-1.5 flex flex-col gap-2">
                {group.thoughts.map((thought) => (
                  <p key={thought.id} className="max-w-[68ch] text-body leading-relaxed text-ink-2">
                    {thought.text}
                  </p>
                ))}
                {group.actions.map((action) => (
                  <LabToolCard key={action.id} form="pill" action={action} copy={copy} />
                ))}
              </div>
            </motion.section>
          )
        })}
      </div>
    </StreamChrome>
  )
}
