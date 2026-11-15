import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { DeliveryGatePayload, UnknownItemPayload, VariantPayload } from '../../api/types'
import type { DomainVerdictPayload } from '../../schemas/optimize'
import type { ThinkingItem } from '../../schemas/stream'
import { AskFlow } from './AskFlow'
import { AssistantBlock } from './AssistantBlock'
import { PhaseLedger } from './PhaseLedger'
import { PHASES, buildPhaseRows } from './turnThinking'
import styles from './ChatStream.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

/** 思考静默多久后提示「正在规划下一步」。 */
const IDLE_HINT_MS = 1500

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
  /** 纯回答轮正文（2026-11-05）：本轮只回答、不产出方案，与 variant 互斥。 */
  replyText: string
  questions: readonly UnknownItemPayload[]
  cleared: readonly string[]
  /** 本轮唯一方案（契约 variant；null 表示未产出）。 */
  variant: VariantPayload | null
  /** 交付证据门结果（2026-11-05 形态层）：null 表示本轮未过门。 */
  deliveryGate: DeliveryGatePayload | null
  /** 领域路由结论（2026-11-14 领域包）：缺省视为旧会话。 */
  domainVerdict?: DomainVerdictPayload | null
  elapsedSeconds: number | null
  errorMessage: string | null
  isBusy: boolean
  onSubmitAnswers: (answers: Record<string, string>) => void
  onEscape: () => void
  onGuardrail: (action: 'continue' | 'generate') => void
}

/**
 * 正式界面对话流（2026-11-07 终端工具版）：
 * 用户气泡 → 助手块（品牌行 + 执行账本 + 分隔线 + 正文）。
 *
 * 过程区默认展开（含结束后），由用户手动折叠成一行摘要；正文区只留可直接
 * 发给 Agent 的提示词。纯展示组件：不做评分/阈值/推荐判定（MUST-08）。
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
  variant,
  deliveryGate,
  domainVerdict,
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
  // 中止行只在真中止时出现。
  const hadAsk = questions.length > 0 || cleared.length > 0

  // 过程区：运行中展开，正常结束自动收成一行摘要（2026-11-15 用户裁定）；
  // 用户手动动过之后本轮不再自动改（手动优先）。
  const hasProcess = thinking.length > 0
  const [isProcessOpen, setProcessOpen] = useState(true)
  const userToggledRef = useRef(false)
  useEffect(() => {
    if (userToggledRef.current) return
    if (isThinking) {
      setProcessOpen(true) // 运行中保持展开
      return
    }
    // 只在一轮正常结束时折叠；ask（等答复）、aborted、出错都保持展开
    if (isResult && status === 'done' && errorMessage === null) {
      setProcessOpen(false)
    }
  }, [isThinking, isResult, status, errorMessage])

  const actionCount = thinking.filter((item) => item.kind === 'action').length
  const stepCount = PHASES.filter((phase) =>
    thinking.some((item) => (item.phase === '' ? state : item.phase) === phase),
  ).length
  // 打字机只作用于「正在写的那一条」：最后一条文字且仍在流式中
  const lastTextId = [...thinking].reverse().find((item) => item.kind === 'text')?.id ?? null
  const animatingId = isThinking && lastTextId !== null ? lastTextId : null

  const rows = buildPhaseRows({ thinking, state, translate: t, isLive: true, hadAsk })

  // 恢复的旧会话没有 elapsed（不伪造耗时），此时摘要省略秒数段
  const summary =
    elapsedSeconds !== null
      ? t('chat.process_summary', {
          phase: t(`chat.phase.${state}.label`),
          actions: actionCount,
          seconds: `${elapsedSeconds}s`,
        })
      : t('chat.process_summary_short', {
          phase: t(`chat.phase.${state}.label`),
          actions: actionCount,
        })

  return (
    <div className={s('chat-stream')}>
      {sentence.trim() !== '' ? (
        <div className={s('chat-stream__row chat-stream__row--user')}>
          <div className={s('chat-user-bubble')}>{sentence}</div>
        </div>
      ) : null}

      <AssistantBlock
        ariaLabel={t('chat.aria_reply')}
        header={
          elapsedSeconds !== null ? (
            <span className={s('chat-reply__elapsed')}>
              {t('chat.elapsed', { seconds: elapsedSeconds })}
            </span>
          ) : null
        }
        processControls={
          hasProcess ? (
            <div className={s('chat-reply__process-bar')}>
              <span className={s('chat-reply__process-title')}>
                {t('chat.phases')}
                {!isProcessOpen && actionCount > 0 ? (
                  <span className={s('chat-reply__process-count')}>
                    {t('chat.step_count', { steps: stepCount })}
                  </span>
                ) : null}
              </span>
              <button
                type="button"
                className={s('chat-reply__process-toggle')}
                aria-expanded={isProcessOpen}
                onClick={() => {
                  userToggledRef.current = true
                  setProcessOpen((open) => !open)
                }}
              >
                <span>{isProcessOpen ? t('chat.process_fold') : summary}</span>
                <span className={s('chat-reply__process-caret')} aria-hidden="true">
                  {isProcessOpen ? '▾' : '▸'}
                </span>
              </button>
            </div>
          ) : null
        }
        timeline={isProcessOpen ? <PhaseLedger rows={rows} animatingId={animatingId} /> : null}
        planning={
          isThinking && isIdle ? (
            <p className={s('chat-reply__planning')}>{t('chat.planning')}</p>
          ) : null
        }
        gate={isThinking ? null : deliveryGate}
        domainVerdict={domainVerdict}
        variant={isThinking ? null : variant}
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
