import type { LabCopy } from '../labCopy'
import { cx } from '../utils'

interface LabSidebarProps {
  copy: LabCopy
}

/**
 * 侧边栏标本：分组 + 选中态用「2px 竖线 + 极浅底」而不是整行高亮；
 * 置顶用图形标记，操作用悬浮出现（lab 里常驻展示，便于观察密度）。
 */
export function LabSidebar({ copy }: LabSidebarProps) {
  return (
    <aside className="flex w-full max-w-[264px] flex-col gap-2 rounded-card border border-line bg-surface p-2">
      <header className="flex items-center gap-2 px-1">
        <span className="font-mono text-micro tracking-[0.16em] text-ink-3 uppercase">
          {copy.sidebar.label}
        </span>
        <span className="ml-auto font-mono text-micro text-ink-4">4</span>
      </header>

      <button
        type="button"
        className="flex items-center justify-center gap-1.5 rounded-chip border border-line bg-canvas px-2 py-1.5 text-meta text-ink-2 hover:border-line-strong"
      >
        <span aria-hidden="true">＋</span>
        {copy.sidebar.newSession}
      </button>

      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-1.5 px-1 pt-1">
          <span aria-hidden="true" className="text-ink-4">
            ▾
          </span>
          <span className="truncate font-mono text-micro text-ink-3">{copy.start.folder}</span>
          <span className="ml-auto font-mono text-micro text-ink-4">4</span>
        </div>
        <ul className="flex flex-col">
          {copy.sidebar.items.map((item, index) => {
            const isSelected = index === 0
            return (
              <li key={item} className="relative">
                {isSelected ? (
                  <span
                    aria-hidden="true"
                    className="absolute inset-y-[2px] left-0 w-[2px] rounded-round bg-accent"
                  />
                ) : null}
                <div
                  className={cx(
                    'group flex items-center gap-2 rounded-chip py-1.5 pr-1.5 pl-3',
                    isSelected ? 'bg-selected text-ink' : 'text-ink-2 hover:bg-hover',
                  )}
                >
                  <span className="min-w-0 flex-1 truncate text-meta">{item}</span>
                  {index === 1 ? (
                    <span
                      className="shrink-0 text-ink-4"
                      aria-label={copy.sidebar.pinned}
                      title={copy.sidebar.pinned}
                    >
                      <svg width="11" height="11" viewBox="0 0 16 16" aria-hidden="true">
                        <path
                          d="M8 2l1.5 3.4 3.5.4-2.6 2.3.7 3.4L8 9.8 4.9 11.5l.7-3.4L3 5.8l3.5-.4z"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.2"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </span>
                  ) : null}
                  <span className="shrink-0 font-mono text-micro text-ink-4">18:0{index + 2}</span>
                </div>
              </li>
            )
          })}
        </ul>
      </div>

      <div className="mt-auto flex items-center justify-between border-t border-divider px-1 pt-2">
        <span className="text-micro text-ink-3">{copy.sidebar.history}</span>
        <span className="font-mono text-micro text-ink-4">12</span>
      </div>
    </aside>
  )
}
