import { useEffect, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import type { FollowupRequest } from '../api/types'
import { getHistory, getResult, postFeedback, postFollowup, postOptimize } from '../api/endpoints'
import { ChatStream } from '../components/optimize/ChatStream'
import { ConsoleInput } from '../components/optimize/ConsoleInput'
import { errorMessage } from '../components/settings/errorMessage'
import { useSSE } from '../hooks/useSSE'
import { useOptimizeStore } from '../stores/useOptimizeStore'
import { usePreferenceStore } from '../stores/usePreferenceStore'
import type { VariantLevel } from '../types'

type FlowView = 'input' | 'asking' | 'result'

/** 三态容器视图选择（仅按后端 status 镜像渲染；状态转移逻辑唯一在后端，MUST-07）。 */
function resolveFlowView(status: string | null): FlowView {
  if (status === null) return 'input'
  if (status === 'done' || status === 'aborted') return 'result'
  return 'asking'
}

/** 契约枚举收窄（level 契约为自由字符串，反馈请求仅接受 A/B/C；集合匹配非业务判定）。 */
function toVariantLevel(level: string): VariantLevel | null {
  return level === 'A' || level === 'B' || level === 'C' ? level : null
}

/** 错误文案走统一降级链（按 code 查表 → 后端 message → fallback，N-7）。 */
function toMessage(error: unknown): string {
  return errorMessage(error, '请求失败')
}

/** 优化主页（设计文档 §1.1 对话流：无会话时居中输入卡片，有会话时图五对话流）。 */
export function OptimizePage() {
  const {
    sessionId,
    state,
    status,
    message,
    questions,
    cleared,
    variants,
    ranking,
    target,
    facts,
    isSubmitting,
  } = useOptimizeStore(
    useShallow((s) => ({
      sessionId: s.sessionId,
      state: s.state,
      status: s.status,
      message: s.message,
      questions: s.questions,
      cleared: s.cleared,
      variants: s.variants,
      ranking: s.ranking,
      target: s.target,
      facts: s.facts,
      isSubmitting: s.isSubmitting,
    })),
  )

  const [sentence, setSentence] = useState('')
  const [project, setProject] = useState('')
  const [isBusy, setIsBusy] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [elapsedSeconds, setElapsedSeconds] = useState<number | null>(null)

  useSSE(sessionId)

  // 服务端权威恢复（GET /result）：store 里已有流程即重建快照；失败保持现状，不重试（MUST-15）
  useEffect(() => {
    const activeSessionId = useOptimizeStore.getState().sessionId
    if (!activeSessionId) return undefined
    let isCancelled = false
    getResult(activeSessionId)
      .then((snapshot) => {
        if (!isCancelled) useOptimizeStore.getState().applySnapshot(snapshot)
      })
      .catch((error: unknown) => {
        if (!isCancelled) setErrorMessage(toMessage(error))
      })
    return () => {
      isCancelled = true
    }
  }, [])

  // 耗时计时：自提交时刻起每秒推进，DONE/ABORTED 后冻结（恢复的旧会话无 startedAt 仅显状态）。
  useEffect(() => {
    if (startedAt === null) return undefined
    if (status === 'done' || status === 'aborted') return undefined
    const tick = () => setElapsedSeconds(Math.round((Date.now() - startedAt) / 1000))
    tick()
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [startedAt, status])

  /** 当前首选档位（编辑后采纳 / 👍 用）：后端标记的档位，否则首个方案；渲染门非业务判定（MUST-08）。 */
  function primaryLevel(): VariantLevel | null {
    const store = useOptimizeStore.getState()
    const marked = store.ranking?.marked ? store.ranking.variant : null
    const raw = marked ?? store.variants[0]?.level ?? ''
    return toVariantLevel(raw)
  }

  async function runFollowup(body: FollowupRequest): Promise<void> {
    const activeSessionId = useOptimizeStore.getState().sessionId
    if (!activeSessionId) return
    setIsBusy(true)
    setErrorMessage(null)
    try {
      const snapshot = await postFollowup(activeSessionId, body)
      useOptimizeStore.getState().applySnapshot(snapshot)
    } catch (error) {
      setErrorMessage(toMessage(error))
    } finally {
      setIsBusy(false)
    }
  }

  async function handleOptimizeSubmit(nextSentence: string, nextProject: string): Promise<void> {
    const store = useOptimizeStore.getState()
    store.setSubmitting(true)
    setSentence(nextSentence)
    setProject(nextProject)
    setStartedAt(Date.now())
    setElapsedSeconds(0)
    setErrorMessage(null)
    try {
      const snapshot = await postOptimize({ sentence: nextSentence, project: nextProject })
      store.applySnapshot(snapshot)
      const items = await getHistory().catch(() => null)
      if (items !== null) usePreferenceStore.getState().setHistory(items)
    } catch (error) {
      setErrorMessage(toMessage(error))
    } finally {
      store.setSubmitting(false)
    }
  }

  /** 重跑同一句（复用提交路径，防重靠提交中禁用，MUST-15）。 */
  function handleRetry(): void {
    if (sentence.trim() === '' || project.trim() === '') return
    void handleOptimizeSubmit(sentence, project)
  }

  async function handleFeedback(variant: VariantLevel | null): Promise<void> {
    const activeSessionId = useOptimizeStore.getState().sessionId
    if (!activeSessionId) return
    setIsBusy(true)
    setErrorMessage(null)
    try {
      await postFeedback({
        session_id: activeSessionId,
        action: variant === null ? 'skip' : 'adopt',
        variant,
      })
    } catch (error) {
      setErrorMessage(toMessage(error))
    } finally {
      setIsBusy(false)
    }
  }

  function handleThumb(isUp: boolean): void {
    if (!isUp) {
      void handleFeedback(null)
      return
    }
    const level = primaryLevel()
    if (level !== null) void handleFeedback(level)
  }

  const view = resolveFlowView(status)

  return (
    <div className="optimize-page">
      {view === 'input' ? (
        <div className="optimize-page__center">
          <ConsoleInput
            isSubmitting={isSubmitting || isBusy}
            onSubmit={(nextSentence, nextProject) => {
              void handleOptimizeSubmit(nextSentence, nextProject)
            }}
          />
          {errorMessage !== null ? <p className="thread__error">{errorMessage}</p> : null}
        </div>
      ) : (
        <ChatStream
          state={state}
          status={status}
          sentence={sentence}
          message={message}
          questions={questions}
          cleared={cleared}
          variants={variants}
          ranking={ranking}
          target={target}
          facts={facts}
          elapsedSeconds={elapsedSeconds}
          errorMessage={errorMessage}
          isBusy={isBusy || isSubmitting}
          canRetry={sentence.trim() !== '' && project.trim() !== ''}
          onSubmitAnswers={(answers) => void runFollowup({ answers, escape: false })}
          onEscape={() => void runFollowup({ escape: true })}
          onGuardrail={(action) => void runFollowup({ escape: false, guardrail_action: action })}
          onAdopt={(level) => void handleFeedback(level)}
          onEditAdopt={() => {
            const level = primaryLevel()
            if (level !== null) void handleFeedback(level)
          }}
          onSkip={() => void handleFeedback(null)}
          onThumb={handleThumb}
          onRetry={handleRetry}
        />
      )}
    </div>
  )
}
