import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type {
  DeliveryGatePayload,
  RankingViewPayload,
  UnknownItemPayload,
  VariantPayload,
} from '../../api/types'
import type { ThinkingItem } from '../../schemas/stream'
import { AskFlow } from './AskFlow'
import { AssistantBlock } from './AssistantBlock'
import { TraceEntry } from './TraceEntry'
import './ChatStream.css'

/** 思考静默多久后提示「正在规划下一步」。 */
const IDLE_HINT_MS = 1500

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

/** 状态的展示键与「这一步在做什么」说明键（文案在语言包，2026-11-06 多语言）。 */
const PHASE_META: Record<(typeof PHASES)[number], { labelKey: string; hintKey: string }> = {
  INIT: { labelKey: 'chat.phase.INIT.label', hintKey: 'chat.phase.INIT.hint' },
  RETRIEVING: { labelKey: 'chat.phase.RETRIEVING.label', hintKey: 'chat.phase.RETRIEVING.hint' },
  PROBING: { labelKey: 'chat.phase.PROBING.label', hintKey: 'chat.phase.PROBING.hint' },
  ASKING: { labelKey: 'chat.phase.ASKING.label', hintKey: 'chat.phase.ASKING.hint' },
  CONFIRMING: { labelKey: 'chat.phase.CONFIRMING.label', hintKey: 'chat.phase.CONFIRMING.hint' },
  GENERATING: { labelKey: 'chat.phase.GENERATING.label', hintKey: 'chat.phase.GENERATING.hint' },
  RANKING: { labelKey: 'chat.phase.RANKING.label', hintKey: 'chat.phase.RANKING.hint' },
  DONE: { labelKey: 'chat.phase.DONE.label', hintKey: 'chat.phase.DONE.hint' },
  ABORTED: { labelKey: 'chat.phase.ABORTED.label', hintKey: 'chat.phase.ABORTED.hint' },
}

interface PhaseLogProps {
  items: readonly ThinkingItem[]
}

/** 某一阶段下方的过程：文字段落 + 真实工具卡片（2026-10-20）。 */
function PhaseLog({ items }: PhaseLogProps) {
  if (items.length === 0) return null
  return (
    <div className="chat-reply__phase-log">
      {items.map((item) => (
        <TraceEntry key={item.id} item={item} />
      ))}
    </div>
  )
}

interface ChatStreamProps {
  /** 当前态镜像（后端 9 态字符串）；仅展示不判定（MUST-07）。 */
  state: string
  /** 快照状态镜像（ask / done / guardrail / aborted）。 */
  status: string | null
  /** 会话原句（用户气泡内容；提交时本地记录，恢复的旧会话可能为空）。 */
  sentence: string
  /** 思考过程时间线（带阶段标签，按阶段挂到对应步骤下）。 */
  thinking: readonly ThinkingItem[]
  /** 思考流进行中：正文区暂不渲染反问/结果。 */
  isThinking: boolean
  message: string
  /** 纯回答轮正文（2026-11-05）：本轮只回答、不产出方案，与 variants 互斥。 */
  replyText: string
  questions: readonly UnknownItemPayload[]
  cleared: readonly string[]
  variants: readonly VariantPayload[]
  ranking: RankingViewPayload | null
  /** 未产生推荐的原因（2026-11-06）：透传给 ConfidenceNotice 区分「单套跳过」与「打分失败」。 */
  rankingSkipReason?: string | null
  /** 交付证据门结果（2026-11-05 形态层）：null 表示本轮未过门。 */
  deliveryGate: DeliveryGatePayload | null
  elapsedSeconds: number | null
  errorMessage: string | null
  isBusy: boolean
  onSubmitAnswers: (answers: Record<string, string>) => void
  onEscape: () => void
  onGuardrail: (action: 'continue' | 'generate') => void
}

/**
 * 正式界面对话流（2026-10-20 v2）：
 * 用户气泡 → 回复块（品牌行 + 步骤时间轴（每步下方挂过程）+ 分隔线 + 正文）。
 *
 * 按用户要求移除了目标定位、取证事实、采纳/跳过操作栏与底部图标行——只留可直接发给
 * Agent 的提示词正文。纯展示组件：不做评分/阈值/推荐判定（MUST-08）。
 */
export function ChatStream({
  state,
  status,
  sentence,
  thinking,
  isThinking,
  message,
  replyText,
  questions,
  cleared,
  variants,
  ranking,
  rankingSkipReason = null,
  deliveryGate,
  elapsedSeconds,
  errorMessage,
  isBusy,
  onSubmitAnswers,
  onEscape,
  onGuardrail,
}: ChatStreamProps) {
  const { t } = useTranslation()
  const isResult = status === 'done' || status === 'aborted'
  // 思考静默 1.5s 后提示「正在规划下一步」：新事件到达即消失（纯前端状态）
  const [isIdle, setIdle] = useState(false)
  useEffect(() => {
    if (!isThinking) {
      setIdle(false)
      return undefined
    }
    setIdle(false)
    const timer = window.setTimeout(() => setIdle(true), IDLE_HINT_MS)
    return () => window.clearTimeout(timer)
  }, [isThinking, thinking.length])
  // 阶段按**实际走过的路径**渲染（2026-11-04）：没问过就不出现「等待确认 / 整理答复」，
  // 单套方案按 MUST-28 跳过打分故不出现「评估推荐」，中止行只在真中止时出现。
  const hadAsk = questions.length > 0 || cleared.length > 0
  const willRank = ranking !== null || variants.length > 1
  const visiblePhases = PHASES.filter((phase) => {
    if (phase === 'ASKING' || phase === 'CONFIRMING') return hadAsk
    if (phase === 'RANKING') return willRank
    if (phase === 'ABORTED') return state === 'ABORTED'
    return true
  })
  const currentIndex = visiblePhases.findIndex((phase) => phase === state)
  // 过程整组折叠（2026-11-04，对齐 CodeBuddy v2.81）：结束/等待答复后收成一行摘要，
  // 点击展开回看；进行中永远展开。status 每次变化若可折叠则复位为收起。
  const canCollapse = thinking.length > 0 && !isThinking && (status === 'done' || status === 'ask')
  const [isProcessOpen, setProcessOpen] = useState(false)
  useEffect(() => {
    if (canCollapse) setProcessOpen(false)
  }, [canCollapse])
  const showProcess = !canCollapse || isProcessOpen
  const actionCount = thinking.filter((item) => item.kind === 'action').length
  const stepCount = PHASES.filter((phase) =>
    thinking.some((item) => (item.phase === '' ? state : item.phase) === phase),
  ).length

  return (
    <div className="chat-stream">
      {sentence.trim() !== '' ? (
        <div className="chat-stream__row chat-stream__row--user">
          <div className="chat-user-bubble">{sentence}</div>
        </div>
      ) : null}

      <AssistantBlock
        ariaLabel={t('chat.aria_reply')}
        header={
          elapsedSeconds !== null ? (
            <span className="chat-reply__elapsed">
              {t('chat.elapsed', { seconds: elapsedSeconds })}
            </span>
          ) : null
        }
        processToggle={
          canCollapse ? (
            <button
              type="button"
              className="chat-reply__process-toggle"
              aria-expanded={isProcessOpen}
              onClick={() => setProcessOpen((open) => !open)}
            >
              <span className="chat-reply__process-caret" aria-hidden="true">
                {isProcessOpen ? '▾' : '▸'}
              </span>
              <span>
                {t('chat.thinking_meta', {
                  seconds: elapsedSeconds !== null ? `${elapsedSeconds}s` : t('chat.done'),
                  actions: actionCount,
                  steps: stepCount,
                })}
              </span>
            </button>
          ) : null
        }
        timeline={
          showProcess ? (
            <ol className="chat-reply__phases" aria-label={t('chat.phases')}>
              {visiblePhases.map((phase, index) => {
                const isDone = index < currentIndex
                const isCurrent = phase === state
                const metaItem = PHASE_META[phase]
                // 没有缺口时，研判这一步给出「无需补充」的结论文案，而不是暗示存在缺口
                const hint =
                  phase === 'PROBING' && !hadAsk ? t('chat.probe_complete') : t(metaItem.hintKey)
                // 无阶段标签的旧数据归到当前阶段，避免过程凭空消失
                const logs = thinking.filter(
                  (item) => (item.phase === '' ? state : item.phase) === phase,
                )
                return (
                  <li
                    key={phase}
                    className={
                      isCurrent
                        ? 'chat-reply__phase chat-reply__phase--current'
                        : isDone
                          ? 'chat-reply__phase chat-reply__phase--done'
                          : 'chat-reply__phase'
                    }
                    aria-current={isCurrent ? 'step' : undefined}
                  >
                    <div className="chat-reply__phase-head">
                      <span className="chat-reply__phase-mark" aria-hidden="true">
                        {isDone ? '✓' : isCurrent ? '●' : '○'}
                      </span>
                      <span className="chat-reply__phase-label">{t(metaItem.labelKey)}</span>
                      <span className="chat-reply__phase-hint">{hint}</span>
                      {isCurrent ? (
                        <span className="chat-reply__phase-tag">
                          {phase === 'DONE'
                            ? t('chat.tag_done')
                            : phase === 'ABORTED'
                              ? t('chat.tag_aborted')
                              : t('chat.tag_running')}
                        </span>
                      ) : null}
                    </div>
                    <PhaseLog items={logs} />
                  </li>
                )
              })}
            </ol>
          ) : null
        }
        planning={
          isThinking && isIdle ? <p className="chat-reply__planning">{t('chat.planning')}</p> : null
        }
        gate={isThinking ? null : deliveryGate}
        variants={isThinking ? [] : variants}
        ranking={isThinking ? null : ranking}
        rankingSkipReason={isThinking ? null : rankingSkipReason}
        replyText={isThinking ? '' : replyText}
        message={!isThinking && isResult ? message : ''}
        error={errorMessage ?? undefined}
      >
        {isThinking ? null : isResult ? null : (
          <AskFlow
            questions={questions}
            cleared={cleared}
            status={status}
            isBusy={isBusy}
            onSubmitAnswers={onSubmitAnswers}
            onEscape={onEscape}
            onGuardrail={onGuardrail}
          />
        )}
      </AssistantBlock>
    </div>
  )
}
