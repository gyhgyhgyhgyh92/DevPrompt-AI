import { useEffect, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import type { FollowupRequest } from '../api/types'
import {
  getHistory,
  getPreference,
  getResult,
  postFeedback,
  postFollowup,
  postOptimize,
} from '../api/endpoints'
import { ConfidenceNotice } from '../components/optimize/ConfidenceNotice'
import { ConsoleInput } from '../components/optimize/ConsoleInput'
import { ContextPanel } from '../components/optimize/ContextPanel'
import { FollowupForm } from '../components/optimize/FollowupForm'
import { PhaseIndicator } from '../components/optimize/PhaseIndicator'
import { VariantTabs } from '../components/optimize/VariantTabs'
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

function toMessage(error: unknown): string {
  return error instanceof Error ? error.message : '请求失败'
}

/** 优化主页工作台（设计文档 §1.1 三栏：会话侧栏 / 流程线程 / 上下文面板）。 */
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
  const vector = usePreferenceStore((s) => s.vector)

  const [sentence, setSentence] = useState('')
  const [isBusy, setIsBusy] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

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

  // 上下文面板偏好条数据（页面编排调 API，store 只存结果）；会话列表由侧边栏负责
  useEffect(() => {
    getPreference()
      .then((preference) => usePreferenceStore.getState().setVector(preference))
      .catch(() => {
        // 偏好条加载失败保持空态，不重试
      })
  }, [])

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

  async function handleOptimizeSubmit(nextSentence: string, project: string): Promise<void> {
    const store = useOptimizeStore.getState()
    store.setSubmitting(true)
    setErrorMessage(null)
    try {
      const snapshot = await postOptimize({ sentence: nextSentence, project })
      store.applySnapshot(snapshot)
      const items = await getHistory().catch(() => null)
      if (items !== null) usePreferenceStore.getState().setHistory(items)
    } catch (error) {
      setErrorMessage(toMessage(error))
    } finally {
      store.setSubmitting(false)
    }
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

  const view = resolveFlowView(status)

  return (
    <div className="optimize-page">
      {view === 'input' ? (
        <div className="optimize-page__center">
          <ConsoleInput
            isSubmitting={isSubmitting || isBusy}
            onSubmit={(nextSentence, project) => {
              setSentence(nextSentence)
              void handleOptimizeSubmit(nextSentence, project)
            }}
          />
          {errorMessage !== null ? <p className="thread__error">{errorMessage}</p> : null}
        </div>
      ) : (
        <div className="workspace workspace--chat">
          <section className="workspace__thread" aria-label="流程线程">
            <h1>优化流程</h1>
            <PhaseIndicator state={state} />
            {sentence.trim() !== '' ? <p className="thread__bubble">{sentence}</p> : null}
            {errorMessage !== null ? <p className="thread__error">{errorMessage}</p> : null}

            {view === 'asking' ? (
              <FollowupForm
                questions={questions}
                cleared={cleared}
                status={status}
                isBusy={isBusy || isSubmitting}
                onSubmitAnswers={(answers) => void runFollowup({ answers, escape: false })}
                onEscape={() => void runFollowup({ escape: true })}
                onGuardrail={(action) =>
                  void runFollowup({ escape: false, guardrail_action: action })
                }
              />
            ) : null}

            {view === 'result' ? (
              <div>
                {message !== '' ? <p className="thread__message">{message}</p> : null}
                <ConfidenceNotice ranking={ranking} />
                <VariantTabs
                  variants={variants}
                  ranking={ranking}
                  renderActions={(variant) => {
                    const level = toVariantLevel(variant.level)
                    return level === null ? null : (
                      <button
                        type="button"
                        className="button button--primary"
                        disabled={isBusy || isSubmitting}
                        onClick={() => void handleFeedback(level)}
                      >
                        采纳 {variant.level}
                      </button>
                    )
                  }}
                />
                <div className="thread__actions">
                  <button
                    type="button"
                    className="button button--ghost"
                    disabled={isBusy || isSubmitting}
                    onClick={() => void handleFeedback(null)}
                  >
                    跳过
                  </button>
                </div>
              </div>
            ) : null}
          </section>
          <ContextPanel target={target} facts={facts} vector={vector} />
        </div>
      )}
    </div>
  )
}
