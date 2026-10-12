import { useState } from 'react'
import type {
  FlowSnapshotResponse,
  RankingViewPayload,
  UnknownItemPayload,
  VariantPayload,
} from '../../api/types'
import type { VariantLevel } from '../../types'
import { ConfidenceNotice } from './ConfidenceNotice'
import { FollowupForm } from './FollowupForm'
import { VariantTabs } from './VariantTabs'
import './ChatStream.css'

/** 契约载荷按生成类型派生（F-705：勿手写结构）。 */
type SymbolPayload = NonNullable<FlowSnapshotResponse['target']>
type FactPayload = NonNullable<FlowSnapshotResponse['facts']>[number]

/** 状态机 9 态展示顺序（后端 state.py FlowState 顺序）；仅用于阶段列表排布，转移逻辑唯一在后端（MUST-07）。 */
const PHASES = [
  'INIT',
  'RETRIEVING',
  'PROBING',
  'ASKING',
  'CONFIRMING',
  'GENERATING',
  'RANKING',
  'DONE',
  'ABORTED',
] as const

/** 契约枚举收窄（level 契约为自由字符串，反馈请求仅接受 A/B/C；集合匹配非业务判定）。 */
function toVariantLevel(level: string): VariantLevel | null {
  return level === 'A' || level === 'B' || level === 'C' ? level : null
}

/** 目标定位展示：symbol@path[:line]；line 为 0 表示后端未带行号（契约默认值语义）。 */
function formatTarget(target: SymbolPayload): string {
  return target.line > 0
    ? `${target.name}@${target.path}:${target.line}`
    : `${target.name}@${target.path}`
}

function BrandMark() {
  return (
    <span className="chat-reply__icon" aria-hidden="true">
      <svg width="12" height="12" viewBox="0 0 16 16" focusable="false">
        <path
          d="M5.5 4.5 3 8l2.5 3.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M8.5 11.5H13"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
    </span>
  )
}

function CopyIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <rect x="5.5" y="5.5" width="7" height="8" rx="1.2" fill="none" stroke="currentColor" />
      <path d="M10 3.5H4.5A1 1 0 0 0 3.5 4.5V11" fill="none" stroke="currentColor" />
    </svg>
  )
}

function RetryIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M12.5 8a4.5 4.5 0 1 1-1.6-3.4M12.5 3.5V6H10"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function ThumbUpIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M5 7.5 7.5 3c1 0 1.5.6 1.5 1.5V7h2.6a1 1 0 0 1 1 1.2l-.7 3.6a1 1 0 0 1-1 .8H5M5 7.5V13H3V7.5h2Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.1"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function ThumbDownIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M11 8.5 8.5 13c-1 0-1.5-.6-1.5-1.5V9H4.4a1 1 0 0 1-1-1.2l.7-3.6a1 1 0 0 1 1-.8H11M11 8.5V3h2v5.5h-2Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.1"
        strokeLinejoin="round"
      />
    </svg>
  )
}

interface ContextSectionProps {
  /** 目标定位（契约 target；null 渲染空态）。 */
  target: SymbolPayload | null
  /** 取证事实清单（契约 facts；key + passed 标记 + evidence 只读渲染）。 */
  facts: readonly FactPayload[]
}

/** 上下文信息内嵌小节（原上下文面板的目标定位/取证事实重排进 AI 回复正文；纯只读渲染）。 */
function ContextSection({ target, facts }: ContextSectionProps) {
  return (
    <section className="chat-context" aria-label="上下文信息">
      <div className="chat-context__block">
        <span className="chat-context__label">目标定位</span>
        {target ? (
          <code className="chat-context__target">{formatTarget(target)}</code>
        ) : (
          <span className="chat-context__empty">暂无目标定位</span>
        )}
      </div>
      <div className="chat-context__block">
        <span className="chat-context__label">取证事实</span>
        {facts.length === 0 ? (
          <span className="chat-context__empty">暂无取证事实</span>
        ) : (
          <ul className="chat-context__facts">
            {facts.map((fact) => (
              <li key={fact.key}>
                <span aria-hidden="true">{fact.passed ? '✓' : '✗'}</span>
                <span className="chat-context__fact-key">{fact.key}</span>
                <span className="chat-context__fact-evidence">{fact.evidence}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}

interface ChatStreamProps {
  /** 当前态镜像（后端 9 态字符串）；仅展示不判定（MUST-07）。 */
  state: string
  /** 快照状态镜像（ask / done / guardrail / aborted）。 */
  status: string | null
  /** 会话原句（用户气泡内容；提交时本地记录，恢复的旧会话可能为空）。 */
  sentence: string
  message: string
  questions: readonly UnknownItemPayload[]
  cleared: readonly string[]
  /** 三套方案（契约 variants）。 */
  variants: readonly VariantPayload[]
  ranking: RankingViewPayload | null
  target: SymbolPayload | null
  facts: readonly FactPayload[]
  /** 耗时秒数（前端自提交时刻计时；null 表示无计时，如恢复的旧会话）。 */
  elapsedSeconds: number | null
  errorMessage: string | null
  /** 提交中禁用一切操作按钮（MUST-15 禁重试语义）。 */
  isBusy: boolean
  /** 重跑可用性（无原句/项目时禁用）。 */
  canRetry: boolean
  onSubmitAnswers: (answers: Record<string, string>) => void
  onEscape: () => void
  onGuardrail: (action: 'continue' | 'generate') => void
  /** 采纳某一档位（POST /feedback adopt）。 */
  onAdopt: (level: VariantLevel) => void
  /** 编辑后采纳（无编辑器，映射既有 adopt 路径）。 */
  onEditAdopt: () => void
  /** 跳过（POST /feedback skip）。 */
  onSkip: () => void
  /** 操作栏 👍/👎 反馈。 */
  onThumb: (isUp: boolean) => void
  onRetry: () => void
}

/**
 * 正式界面对话流（图五 1:1，spec Task 6，F-602/F-703）：
 * 用户气泡 → AI 回复块（图标 + 品牌 + 状态/耗时折叠行 + 分隔线 + 正文 + 操作栏）→ 底部建议胶囊。
 * 三套方案/推荐徽章/评分明细/追问卡/上下文信息嵌入回复正文；全部功能与 MUST-26/27/28/08 保留。
 * 纯展示组件：不读取 store、不做任何评分/阈值/推荐判定（MUST-08）。
 */
export function ChatStream({
  state,
  status,
  sentence,
  message,
  questions,
  cleared,
  variants,
  ranking,
  target,
  facts,
  elapsedSeconds,
  errorMessage,
  isBusy,
  canRetry,
  onSubmitAnswers,
  onEscape,
  onGuardrail,
  onAdopt,
  onEditAdopt,
  onSkip,
  onThumb,
  onRetry,
}: ChatStreamProps) {
  const [isDetailOpen, setDetailOpen] = useState(false)
  const [isCopied, setCopied] = useState(false)

  const isResult = status === 'done' || status === 'aborted'
  const currentIndex = PHASES.findIndex((phase) => phase === state)

  async function handleCopy(): Promise<void> {
    const text = variants.map((variant) => variant.body).join('\n\n')
    await navigator.clipboard.writeText(text)
    setCopied(true)
  }

  return (
    <div className="chat-stream">
      {sentence.trim() !== '' ? (
        <div className="chat-stream__row chat-stream__row--user">
          <div className="chat-user-bubble">{sentence}</div>
        </div>
      ) : null}

      <article className="chat-reply" aria-label="AI 回复">
        <header className="chat-reply__head">
          <BrandMark />
          <span className="chat-reply__brand">DevPrompt AI</span>
        </header>

        <button
          type="button"
          className="chat-reply__status"
          aria-expanded={isDetailOpen}
          onClick={() => setDetailOpen((open) => !open)}
        >
          <span className="chat-reply__status-label">状态</span>
          <span className="chat-reply__state">{state}</span>
          {elapsedSeconds !== null ? (
            <span className="chat-reply__elapsed">耗时 {elapsedSeconds}s</span>
          ) : null}
          <span className="chat-reply__caret" aria-hidden="true">
            ›
          </span>
        </button>

        {isDetailOpen ? (
          <ol className="chat-reply__phases" aria-label="流程阶段">
            {PHASES.map((phase, index) => (
              <li
                key={phase}
                className={
                  phase === state
                    ? 'chat-reply__phase chat-reply__phase--current'
                    : 'chat-reply__phase'
                }
                aria-current={phase === state ? 'step' : undefined}
              >
                {index < currentIndex ? `✓ ${phase}` : phase}
              </li>
            ))}
          </ol>
        ) : null}

        <hr className="chat-reply__divider" />

        <div className="chat-reply__body">
          {errorMessage !== null ? <p className="chat-reply__error">{errorMessage}</p> : null}

          {isResult ? (
            <>
              {message !== '' ? <p className="chat-reply__message">{message}</p> : null}
              <ConfidenceNotice ranking={ranking} />
              <VariantTabs variants={variants} ranking={ranking} />
              <div className="chat-suggestions" aria-label="建议操作">
                {variants.map((variant) => {
                  const level = toVariantLevel(variant.level)
                  return level === null ? null : (
                    <button
                      type="button"
                      key={variant.level}
                      className="chat-suggestion"
                      disabled={isBusy}
                      onClick={() => onAdopt(level)}
                    >
                      采纳 {variant.level}
                      <span aria-hidden="true">→</span>
                    </button>
                  )
                })}
                <button
                  type="button"
                  className="chat-suggestion"
                  disabled={isBusy}
                  onClick={onEditAdopt}
                >
                  编辑后采纳
                  <span aria-hidden="true">→</span>
                </button>
                <button
                  type="button"
                  className="chat-suggestion"
                  disabled={isBusy}
                  onClick={onSkip}
                >
                  跳过
                  <span aria-hidden="true">→</span>
                </button>
              </div>
            </>
          ) : (
            <FollowupForm
              questions={questions}
              cleared={cleared}
              status={status}
              isBusy={isBusy}
              onSubmitAnswers={onSubmitAnswers}
              onEscape={onEscape}
              onGuardrail={onGuardrail}
            />
          )}

          <ContextSection target={target} facts={facts} />
        </div>

        <footer className="chat-reply__actions">
          <div className="chat-reply__actions-left">
            <button
              type="button"
              className="chat-reply__action"
              aria-label={isCopied ? '已复制' : '复制'}
              onClick={() => void handleCopy()}
            >
              <CopyIcon />
            </button>
            <button
              type="button"
              className="chat-reply__action"
              aria-label="重试"
              disabled={isBusy || !canRetry}
              onClick={onRetry}
            >
              <RetryIcon />
            </button>
            <button
              type="button"
              className="chat-reply__action"
              aria-label="赞"
              disabled={isBusy}
              onClick={() => onThumb(true)}
            >
              <ThumbUpIcon />
            </button>
            <button
              type="button"
              className="chat-reply__action"
              aria-label="踩"
              disabled={isBusy}
              onClick={() => onThumb(false)}
            >
              <ThumbDownIcon />
            </button>
          </div>
          <span className="chat-reply__generated">由 AI 生成</span>
        </footer>
      </article>
    </div>
  )
}
