import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { type DemoView, elapsedAt, groupDemoByPhase } from '../demoStream'
import type { LabCopy } from '../labCopy'
import { PhaseChip, StreamChrome, StreamEmpty } from './LabStreamShared'
import { LabToolCard } from './LabToolCard'

interface LabStreamDigestProps {
  view: DemoView
  copy: LabCopy
  applied: number
  isPlaying: boolean
  isReduced: boolean
  onPlay: () => void
}

/**
 * V3 折叠摘要：思考中整组只占一行（流光 + 计数），结束后自动展开成完整时间轴。
 * 适合「不关心过程」的用户；展开时用高度动画，避免内容突然顶掉滚动位置。
 */
export function LabStreamDigest({
  view,
  copy,
  applied,
  isPlaying,
  isReduced,
  onPlay,
}: LabStreamDigestProps) {
  const [isManuallyOpen, setManuallyOpen] = useState(false)
  const groups = groupDemoByPhase(view)
  const isOpen = view.isFinished || isManuallyOpen
  const summary = `${copy.stream.phase[view.phase]} · ${view.actions.length} ${copy.stream.actions} · ${elapsedAt(applied)}`

  return (
    <StreamChrome
      label={copy.variants.digest.name}
      note={copy.variants.digest.note}
      isPlaying={isPlaying}
      isFinished={view.isFinished}
      elapsed={elapsedAt(applied)}
      copy={copy}
    >
      {applied === 0 ? (
        <StreamEmpty label={copy.stream.empty} playLabel={copy.controls.play} onPlay={onPlay} />
      ) : null}
      {applied > 0 ? (
        <>
          <button
            type="button"
            onClick={() => setManuallyOpen((open) => !open)}
            aria-expanded={isOpen}
            className="flex w-full items-center gap-2 rounded-chip border border-line bg-surface px-2.5 py-2 text-left"
          >
            <span className="inline-flex size-3 items-center justify-center" aria-hidden="true">
              <span className="size-1.5 rounded-round bg-accent" />
            </span>
            <span className="relative min-w-0 flex-1 overflow-hidden">
              <span className="relative z-10 block truncate font-mono text-micro text-ink-2">
                {summary}
              </span>
              {isPlaying && !isReduced ? (
                <span aria-hidden="true" className="lab-shimmer absolute inset-0 opacity-70" />
              ) : null}
            </span>
            <span className="shrink-0 font-mono text-micro text-ink-4">
              {isOpen ? copy.tools.collapse : copy.tools.expand}
            </span>
            <span className="text-ink-3" aria-hidden="true">
              {isOpen ? '▾' : '▸'}
            </span>
          </button>

          <AnimatePresence initial={false}>
            {isOpen ? (
              <motion.div
                key="digest-body"
                initial={isReduced ? false : { height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={isReduced ? undefined : { height: 0, opacity: 0 }}
                transition={{ duration: 0.24, ease: [0.2, 0.7, 0.3, 1] }}
                className="overflow-hidden"
              >
                <div className="mt-2 flex flex-col gap-3 border-l border-line pl-3">
                  {groups.map((group, index) => (
                    <section key={group.phase} className="flex flex-col gap-1.5">
                      <header className="flex items-center gap-2">
                        <PhaseChip
                          phase={group.phase}
                          isCurrent={group.phase === view.phase && !view.isFinished}
                          isDone={index < groups.length - 1 || view.isFinished}
                          copy={copy}
                        />
                      </header>
                      {group.thoughts.map((thought) => (
                        <p key={thought.id} className="text-body leading-relaxed text-ink-2">
                          {thought.text}
                        </p>
                      ))}
                      {group.actions.map((action) => (
                        <LabToolCard key={action.id} form="pill" action={action} copy={copy} />
                      ))}
                    </section>
                  ))}
                </div>
              </motion.div>
            ) : null}
          </AnimatePresence>
        </>
      ) : null}

      {applied > 0 && !isOpen ? (
        <p className="mt-2 pl-1 text-micro text-ink-4">{copy.stream.digestTail}</p>
      ) : null}
    </StreamChrome>
  )
}
