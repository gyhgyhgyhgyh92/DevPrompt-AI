import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { type DemoView, elapsedAt, groupDemoByPhase } from '../demoStream'
import type { LabCopy } from '../labCopy'
import { PhaseChip, StreamChrome, StreamEmpty } from './LabStreamShared'
import { LabToolCard } from './LabToolCard'

/**
 * 逐字打字：rAF 驱动、每帧批量推进 2~3 字，而不是每字 setState。
 * 关闭（减少动效 / 已结束）时直接返回全文，避免「演示用动效」影响阅读。
 */
function useTypedText(text: string, enabled: boolean): string {
  const [shown, setShown] = useState(enabled ? '' : text)

  useEffect(() => {
    if (!enabled || typeof requestAnimationFrame !== 'function') {
      setShown(text)
      return undefined
    }
    let index = 0
    let frame = 0
    let lastStamp = 0
    setShown('')
    const step = (stamp: number): void => {
      if (stamp - lastStamp >= 30) {
        lastStamp = stamp
        index = Math.min(text.length, index + 2)
        setShown(text.slice(0, index))
        if (index >= text.length) return
      }
      frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [text, enabled])

  return shown
}

function TypedThought({ text, isTyping }: { text: string; isTyping: boolean }) {
  const shown = useTypedText(text, isTyping)
  return (
    <p className="max-w-[68ch] text-body leading-relaxed whitespace-pre-wrap text-ink-2">
      {shown}
      {isTyping && shown.length < text.length ? (
        <span className="lab-caret" aria-hidden="true" />
      ) : null}
    </p>
  )
}

interface LabStreamTypewriterProps {
  view: DemoView
  copy: LabCopy
  applied: number
  isPlaying: boolean
  isReduced: boolean
  onPlay: () => void
}

/** V1 打字机：最接近「模型正在想」，但读长文本时最费注意力（只在过程区使用）。 */
export function LabStreamTypewriter({
  view,
  copy,
  applied,
  isPlaying,
  isReduced,
  onPlay,
}: LabStreamTypewriterProps) {
  const groups = groupDemoByPhase(view)
  const lastThoughtId = view.thoughts.at(-1)?.id
  const isStreaming = isPlaying && !view.isFinished

  return (
    <StreamChrome
      label={copy.variants.typewriter.name}
      note={copy.variants.typewriter.note}
      isPlaying={isPlaying}
      isFinished={view.isFinished}
      elapsed={elapsedAt(applied)}
      copy={copy}
    >
      {applied === 0 ? (
        <StreamEmpty label={copy.stream.empty} playLabel={copy.controls.play} onPlay={onPlay} />
      ) : null}
      <div className="flex flex-col gap-3">
        {groups.map((group, index) => {
          const isCurrent = group.phase === view.phase && !view.isFinished
          const isDone = index < groups.length - 1 || view.isFinished
          return (
            <section key={group.phase} className="flex flex-col gap-1.5">
              <PhaseChip phase={group.phase} isCurrent={isCurrent} isDone={isDone} copy={copy} />
              {group.thoughts.map((thought) => (
                <motion.div
                  key={thought.id}
                  initial={isReduced ? false : { opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.18 }}
                >
                  <TypedThought
                    text={thought.text}
                    isTyping={isStreaming && thought.id === lastThoughtId && !isReduced}
                  />
                </motion.div>
              ))}
              <div className="flex flex-col gap-1.5">
                {group.actions.map((action) => (
                  <LabToolCard key={action.id} form="card" action={action} copy={copy} />
                ))}
              </div>
            </section>
          )
        })}
      </div>
    </StreamChrome>
  )
}
