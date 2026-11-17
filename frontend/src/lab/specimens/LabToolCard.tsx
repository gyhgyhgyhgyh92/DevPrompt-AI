import { useState } from 'react'
import type { DemoActionView } from '../demoStream'
import type { LabCopy } from '../labCopy'
import type { LabToolForm } from '../types'
import { cx } from '../utils'

function formatDuration(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

function ReadGlyph() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M3 4.5h4l1 1.6h5v6.4H3zM3 4.5V12"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function CommandGlyph() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <rect
        x="2.2"
        y="3"
        width="11.6"
        height="10"
        rx="2"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
      />
      <path
        d="M4.8 6.4 6.8 8l-2 1.6M8.4 9.6h2.6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/** 三态字形：运行中 = 转环，成功 = 对勾，失败 = 叉；形状/图标区分，不单靠颜色（色盲可读）。 */
function StatusGlyph({ state }: { state: DemoActionView['status'] | 'running' }) {
  if (state === 'running') {
    return (
      <span className="lab-spin inline-flex size-3 text-accent" aria-hidden="true">
        <svg width="12" height="12" viewBox="0 0 16 16" focusable="false">
          <circle
            cx="8"
            cy="8"
            r="5.4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeDasharray="22 12"
          />
        </svg>
      </span>
    )
  }
  if (state === 'failed') {
    return (
      <svg
        width="12"
        height="12"
        viewBox="0 0 16 16"
        className="text-danger"
        aria-hidden="true"
        focusable="false"
      >
        <path
          d="M4.4 4.4l7.2 7.2M11.6 4.4l-7.2 7.2"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
        />
      </svg>
    )
  }
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 16 16"
      className="text-ok"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M3.6 8.4l2.8 2.8 6-6.4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function statusText(action: DemoActionView, copy: LabCopy): string {
  if (action.isRunning) return copy.stream.running
  return action.status === 'failed' ? copy.stream.failed : copy.stream.done
}

function verbOf(action: DemoActionView, copy: LabCopy): string {
  return action.kind === 'read' ? copy.tools.read : copy.tools.command
}

const SAMPLE_OK: DemoActionView = {
  id: -1,
  phase: 'RETRIEVING',
  isRunning: false,
  kind: 'command',
  target: 'rg -n "setSseStatus" src/',
  scope: '',
  output: 'src/App.tsx:139\nsrc/hooks/useSSE.ts:37',
  durationMs: 42,
  status: 'ok',
}

const SAMPLE_RUNNING: DemoActionView = {
  ...SAMPLE_OK,
  id: -2,
  isRunning: true,
  target: 'pnpm vitest run src/hooks',
  output: '',
  durationMs: 2140,
}

const SAMPLE_FAILED: DemoActionView = {
  ...SAMPLE_OK,
  id: -3,
  kind: 'read',
  target: 'src/domain/ranking/rank.py',
  scope: 'L1-40',
  output: 'FileNotFoundError: no such file or directory',
  durationMs: 12,
  status: 'failed',
}

/** 04 的标本：同一形态并列 ok / running / failed，一眼能看出三态的差别。 */
export function LabToolCardSample({ form, copy }: { form: LabToolForm; copy: LabCopy }) {
  return (
    <div className="flex flex-col gap-1.5">
      <LabToolCard form={form} action={SAMPLE_OK} copy={copy} />
      <LabToolCard form={form} action={SAMPLE_RUNNING} copy={copy} />
      <LabToolCard form={form} action={SAMPLE_FAILED} copy={copy} />
    </div>
  )
}

interface LabToolCardProps {
  form: LabToolForm
  action: DemoActionView
  copy: LabCopy
}

/**
 * 工具卡三形态：同一份动作数据只改信息密度与排布。
 * 三态都显示耗时——「40 秒的安装没有耗时，读起来像 Agent 在发呆」（调研结论）。
 */
export function LabToolCard({ form, action, copy }: LabToolCardProps) {
  const [isOpen, setOpen] = useState(false)
  const state = action.isRunning ? 'running' : action.status
  const duration = action.isRunning ? copy.stream.running : formatDuration(action.durationMs)
  const hasBody = action.output !== ''

  if (form === 'pill') {
    return (
      <div className="overflow-hidden rounded-round border border-line bg-surface">
        <div className="flex items-center gap-2 px-2.5 py-1 text-meta">
          <StatusGlyph state={state} />
          <span className="inline-flex text-ink-3" aria-hidden="true">
            {action.kind === 'read' ? <ReadGlyph /> : <CommandGlyph />}
          </span>
          <span className="text-ink-3">{verbOf(action, copy)}</span>
          <span className="max-w-[190px] truncate font-mono text-micro text-ink-2">
            {action.target}
          </span>
          <span className="ml-auto font-mono text-micro text-ink-3">{duration}</span>
          {hasBody ? (
            <button
              type="button"
              onClick={() => setOpen((open) => !open)}
              aria-expanded={isOpen}
              aria-label={isOpen ? copy.tools.collapse : copy.tools.expand}
              className="text-ink-3 hover:text-ink"
            >
              <span aria-hidden="true">{isOpen ? '▾' : '▸'}</span>
            </button>
          ) : null}
        </div>
        {isOpen && hasBody ? (
          <pre className="overflow-x-auto border-t border-line bg-code px-2.5 py-1.5 font-mono text-micro leading-relaxed text-ink-3">
            {action.output}
          </pre>
        ) : null}
      </div>
    )
  }

  if (form === 'terminal') {
    return (
      <div className="overflow-hidden rounded-chip border border-line bg-code">
        <div className="flex items-center gap-2 border-b border-line px-2.5 py-1.5 font-mono text-micro">
          {/* 读文件不用命令提示符，免得看起来像「执行了 cat」；命令类才显示 $ */}
          <span className="text-ink-4" aria-hidden="true">
            {action.kind === 'read' ? '›' : '$'}
          </span>
          <span className="truncate text-ink-2">{action.target}</span>
          {action.kind === 'command' ? (
            <span
              className={cx(
                'ml-auto rounded-chip border px-1.5 py-px',
                state === 'failed' ? 'border-danger/40 text-danger' : 'border-line text-ink-3',
              )}
            >
              {state === 'failed' ? copy.tools.exitFailed : copy.tools.exitOk}
            </span>
          ) : null}
        </div>
        <pre className="overflow-x-auto px-2.5 py-2 font-mono text-micro leading-relaxed text-ink-3">
          {action.output === '' ? (action.scope !== '' ? action.scope : '—') : action.output}
        </pre>
      </div>
    )
  }

  return (
    <div className="overflow-hidden rounded-card border border-line bg-surface">
      <button
        type="button"
        onClick={() => (hasBody ? setOpen((open) => !open) : undefined)}
        aria-expanded={hasBody ? isOpen : undefined}
        disabled={!hasBody}
        className="flex w-full items-center gap-2 px-2.5 py-2 text-left"
      >
        <span
          className={cx(
            'inline-flex size-6 shrink-0 items-center justify-center rounded-chip border',
            state === 'failed'
              ? 'border-danger/40 bg-danger-soft text-danger'
              : 'border-line bg-code text-ink-2',
          )}
          aria-hidden="true"
        >
          {action.kind === 'read' ? <ReadGlyph /> : <CommandGlyph />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span className="text-meta font-medium text-ink">
              {verbOf(action, copy)}
              {action.scope !== '' ? (
                <span className="ml-1.5 font-mono text-micro text-ink-3">{action.scope}</span>
              ) : null}
            </span>
            <span className="ml-auto font-mono text-micro text-ink-3">{duration}</span>
          </span>
          <span className="mt-[2px] block truncate font-mono text-micro text-ink-2">
            {action.target}
          </span>
        </span>
        <StatusGlyph state={state} />
        {hasBody ? (
          <span className="text-ink-3" aria-hidden="true">
            {isOpen ? '▾' : '▸'}
          </span>
        ) : null}
      </button>
      {isOpen && hasBody ? (
        <pre className="max-h-40 overflow-auto border-t border-line bg-code px-2.5 py-2 font-mono text-micro leading-relaxed text-ink-3">
          {action.output}
        </pre>
      ) : null}
      <div className="flex items-center gap-2 border-t border-line px-2.5 py-1 font-mono text-micro text-ink-4">
        <span>{statusText(action, copy)}</span>
        {hasBody ? (
          <>
            <span aria-hidden="true">·</span>
            <span>{isOpen ? copy.tools.collapse : copy.tools.expand}</span>
          </>
        ) : null}
      </div>
    </div>
  )
}
