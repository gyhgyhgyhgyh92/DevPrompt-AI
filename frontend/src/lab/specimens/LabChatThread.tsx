import type { DemoPhase } from '../demoStream'
import type { LabCopy } from '../labCopy'
import { cx } from '../utils'

/** 已完成轮的阶段账本（数据取自 demo 序列的耗时口径，纯展示）。 */
const PHASE_ROWS: readonly { phase: DemoPhase; meta: string }[] = [
  { phase: 'RETRIEVING', meta: '1.4s · 2' },
  { phase: 'PROBING', meta: '2.3s · 1' },
  { phase: 'GENERATING', meta: '1.1s' },
  { phase: 'RANKING', meta: '0.6s' },
]

function CheckGlyph() {
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

interface LabChatThreadProps {
  copy: LabCopy
}

/**
 * 对话线程骨架：用户气泡 → 助手块（品牌行 / 阶段账本 / 分隔线 / 结论 / 三套方案）。
 * 阶段账本不是进度条：每行给出「做了什么 + 用时」，失败会留在原位（本标本全成功，失败态见 04）。
 */
export function LabChatThread({ copy }: LabChatThreadProps) {
  return (
    <article className="flex min-h-[300px] flex-col gap-3 rounded-card border border-line bg-surface p-3.5">
      <div className="flex justify-end">
        <p className="lab-bubble max-w-[78%] rounded-card bg-bubble px-3 py-2 text-body leading-relaxed text-ink">
          {copy.thread.user}
        </p>
      </div>

      <div className="flex flex-col gap-2.5">
        <header className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block size-2 rounded-[2px] bg-accent" />
          <span className="font-mono text-micro tracking-[0.14em] text-ink-2 uppercase">
            {copy.brand}
          </span>
          <span className="ml-auto font-mono text-micro text-ink-4">{copy.thread.elapsed}</span>
        </header>

        <ol className="flex flex-col gap-1">
          {PHASE_ROWS.map((row) => (
            <li key={row.phase} className="flex items-center gap-2 lab-phase-row">
              <span className="inline-flex text-ok" aria-hidden="true">
                <CheckGlyph />
              </span>
              <span className="lab-phase-label text-meta text-ink-2">
                {copy.stream.phase[row.phase]}
              </span>
              <span className="ml-auto font-mono text-micro text-ink-4">{row.meta}</span>
            </li>
          ))}
        </ol>

        <h4 className="font-mono text-micro tracking-[0.14em] text-ink-4 uppercase">
          {copy.thread.answerTitle}
        </h4>
        <p className="max-w-[68ch] text-body leading-relaxed text-ink-2">{copy.thread.answer}</p>

        <div className="flex flex-col gap-1.5">
          {copy.thread.plans.map((plan, index) => (
            <div
              key={plan}
              className={cx(
                'flex items-center gap-2 rounded-chip border px-2 py-1.5',
                index === 0 ? 'border-accent/40 bg-accent-soft' : 'border-line bg-surface',
              )}
            >
              <span className="shrink-0 font-mono text-micro text-ink-3">
                {copy.thread.planLevels[index]}
              </span>
              <span className="min-w-0 flex-1 truncate text-meta text-ink">{plan}</span>
              {index === 0 ? (
                <span className="shrink-0 rounded-round bg-surface px-1.5 py-px text-micro font-medium text-ink">
                  {copy.thread.recommend}
                </span>
              ) : null}
            </div>
          ))}
        </div>
      </div>

      {/* 结果态常驻输入栏：思考中不禁用入口，只禁用输入并给出「停止生成」 */}
      <div className="mt-auto flex items-center gap-2 rounded-card border border-line bg-code px-2.5 py-1.5">
        <span className="min-w-0 flex-1 truncate text-micro text-ink-4">
          {copy.thread.composerHint}
        </span>
        <span className="shrink-0 rounded-chip border border-line px-1.5 py-px font-mono text-micro text-ink-4">
          deepseek-chat
        </span>
        <button
          type="button"
          className="shrink-0 rounded-chip border border-line bg-surface px-2 py-[2px] text-micro text-ink-2 hover:border-line-strong"
        >
          {copy.thread.stop}
        </button>
      </div>
    </article>
  )
}
