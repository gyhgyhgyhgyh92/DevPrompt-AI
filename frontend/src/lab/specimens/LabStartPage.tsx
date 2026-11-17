import type { LabCopy } from '../labCopy'
import type { LabStartComposition } from '../types'
import { cx } from '../utils'

function FolderGlyph() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M1.6 4.2h4l1 1.4h7.8v6.2a1 1 0 0 1-1 1H2.6a1 1 0 0 1-1-1z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function BrandRow({ copy }: { copy: LabCopy }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span aria-hidden="true" className="inline-block size-2 rounded-[2px] bg-accent" />
      <span className="font-mono text-micro tracking-[0.16em] text-ink-2 uppercase">
        {copy.brand}
      </span>
      <span className="font-mono text-micro text-ink-4">/ {copy.name}</span>
    </span>
  )
}

/** 输入卡：只还原版式与控件，不接任何真实输入（lab 不写业务状态）。 */
function Composer({ copy, isTall }: { copy: LabCopy; isTall: boolean }) {
  return (
    <div className="w-full overflow-hidden rounded-panel border border-line bg-surface shadow-card">
      <textarea
        readOnly
        aria-label={copy.start.send}
        rows={isTall ? 4 : 3}
        placeholder={copy.start.placeholder}
        className="w-full resize-none bg-transparent px-3.5 pt-3 text-body leading-relaxed text-ink placeholder:text-ink-4 focus:outline-none"
      />
      <div className="flex items-center gap-2 px-2.5 pb-2.5">
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-chip border border-line px-2 py-1 text-micro text-ink-2 hover:border-line-strong"
        >
          <FolderGlyph />
          <span className="max-w-[140px] truncate font-mono">{copy.start.folder}</span>
        </button>
        <span className="ml-auto font-mono text-micro text-ink-4">deepseek-chat</span>
        <button
          type="button"
          aria-label={copy.start.send}
          className="inline-flex size-7 items-center justify-center rounded-chip bg-accent text-body text-ink-inverse"
        >
          <span aria-hidden="true">↑</span>
        </button>
      </div>
    </div>
  )
}

interface LabStartPageProps {
  copy: LabCopy
  composition: LabStartComposition
}

/** 启动页标本：两种构图共享同一份文案，只改信息顺序与视觉重心。 */
export function LabStartPage({ copy, composition }: LabStartPageProps) {
  if (composition === 'split') {
    return (
      <div className="lab-grid grid min-h-[300px] grid-cols-1 gap-4 rounded-card border border-line bg-surface p-4 sm:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="flex min-w-0 flex-col justify-center gap-2.5">
          <BrandRow copy={copy} />
          <h3
            className="text-title leading-snug text-ink"
            style={{ fontWeight: 'var(--lab-display-weight)' }}
          >
            {copy.start.headB}
          </h3>
          <p className="text-meta leading-relaxed text-ink-2">{copy.start.subB}</p>
          <div className="mt-1 flex flex-col gap-1">
            <span className="font-mono text-micro tracking-[0.14em] text-ink-4 uppercase">
              {copy.start.recent}
            </span>
            {copy.start.recentItems.map((item, index) => (
              <span
                key={item}
                className={cx(
                  'flex items-center gap-2 rounded-chip px-1.5 py-1 font-mono text-micro',
                  index === 0 ? 'bg-selected text-ink' : 'text-ink-3',
                )}
              >
                <span aria-hidden="true" className="text-ink-4">
                  ▸
                </span>
                {item}
              </span>
            ))}
          </div>
        </div>
        <div className="flex min-w-0 items-center">
          <Composer copy={copy} isTall />
        </div>
      </div>
    )
  }

  return (
    <div className="lab-grid flex min-h-[300px] flex-col items-center justify-center gap-4 rounded-card border border-line bg-surface px-4 py-6 text-center">
      <BrandRow copy={copy} />
      <h3
        className="max-w-[24ch] text-[22px] leading-tight tracking-[-0.01em] text-ink"
        style={{ fontWeight: 'var(--lab-display-weight)' }}
      >
        {copy.start.headA}
      </h3>
      <p className="max-w-[42ch] text-meta leading-relaxed text-ink-2">{copy.start.subA}</p>
      <div className="flex flex-wrap items-center justify-center gap-1.5">
        {copy.start.chips.map((chip) => (
          <span
            key={chip}
            className="rounded-round border border-line px-2 py-[2px] font-mono text-micro text-ink-3"
          >
            {chip}
          </span>
        ))}
      </div>
      <Composer copy={copy} isTall={false} />
    </div>
  )
}
