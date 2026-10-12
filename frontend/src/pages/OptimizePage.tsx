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
import { ContextPanel } from '../components/optimize/ContextPanel'
import { PhaseIndicator } from '../components/optimize/PhaseIndicator'
import { SessionSidebar } from '../components/optimize/SessionSidebar'
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
  const history = usePreferenceStore((s) => s.history)
  const vector = usePreferenceStore((s) => s.vector)

  const [sentence, setSentence] = useState('')
  const [project, setProject] = useState('')
  const [answers, setAnswers] = useState<Record<string, string>>({})
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

  // 侧栏会话列表与上下文面板偏好条数据（页面编排调 API，store 只存结果）
  useEffect(() => {
    getHistory()
      .then((items) => usePreferenceStore.getState().setHistory(items))
      .catch(() => {
        // 列表加载失败保持空态（侧栏已渲染兜底文案），不重试
      })
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

  async function handleOptimizeSubmit(): Promise<void> {
    const store = useOptimizeStore.getState()
    store.setSubmitting(true)
    setErrorMessage(null)
    try {
      const snapshot = await postOptimize({ sentence: sentence.trim(), project: project.trim() })
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

  async function handleSelectSession(selected: string): Promise<void> {
    setIsBusy(true)
    setErrorMessage(null)
    try {
      const snapshot = await getResult(selected)
      useOptimizeStore.getState().applySnapshot(snapshot)
    } catch (error) {
      setErrorMessage(toMessage(error))
    } finally {
      setIsBusy(false)
    }
  }

  function handleNewSession(): void {
    useOptimizeStore.getState().reset()
    setSentence('')
    setAnswers({})
    setErrorMessage(null)
  }

  const view = resolveFlowView(status)

  return (
    <div className="workspace">
      <SessionSidebar
        sessions={history}
        onSelectSession={(selected) => void handleSelectSession(selected)}
        onNewSession={handleNewSession}
      />
      <section className="workspace__thread" aria-label="流程线程">
        <h1>优化流程</h1>
        <PhaseIndicator state={state} />
        {sentence.trim() !== '' ? <p className="thread__bubble">{sentence}</p> : null}
        {errorMessage !== null ? <p className="thread__error">{errorMessage}</p> : null}

        {view === 'input' ? (
          <form
            className="thread__form"
            onSubmit={(event) => {
              event.preventDefault()
              void handleOptimizeSubmit()
            }}
          >
            <label className="field">
              <span>项目路径</span>
              <input
                className="field__input"
                value={project}
                onChange={(event) => setProject(event.target.value)}
                placeholder="D:/workspace/repo"
              />
            </label>
            <label className="field">
              <span>优化原句</span>
              <textarea
                className="field__textarea"
                value={sentence}
                onChange={(event) => setSentence(event.target.value)}
                placeholder="描述要改造的目标……"
                rows={4}
              />
            </label>
            <button
              type="submit"
              className="button button--primary"
              disabled={isSubmitting || isBusy || sentence.trim() === '' || project.trim() === ''}
            >
              {isSubmitting ? '提交中…' : '开始优化'}
            </button>
          </form>
        ) : null}

        {view === 'asking' ? (
          <div>
            {status === 'guardrail' ? (
              <div className="guardrail-banner">
                <p>软护栏触发：请裁决继续追问或直接生成</p>
                <button
                  type="button"
                  className="button button--ghost"
                  disabled={isBusy}
                  onClick={() => void runFollowup({ escape: false, guardrail_action: 'continue' })}
                >
                  继续追问
                </button>
                <button
                  type="button"
                  className="button button--primary"
                  disabled={isBusy}
                  onClick={() => void runFollowup({ escape: false, guardrail_action: 'generate' })}
                >
                  直接生成
                </button>
              </div>
            ) : null}
            {cleared.length > 0 ? (
              <p className="thread__chips">
                <span>已澄清：</span>
                {cleared.map((key) => (
                  <span className="thread__chip" key={key}>
                    {key}
                  </span>
                ))}
              </p>
            ) : null}
            <ul className="clarify-list">
              {questions.map((item) => (
                <li className="clarify-card" key={item.key}>
                  <span className="clarify-card__key">{item.key}</span>
                  <p className="clarify-card__reason">{item.reason}</p>
                  <p className="clarify-card__guess">
                    <span>当前最佳推断：{item.best_guess}</span>
                    <button
                      type="button"
                      className="button button--ghost"
                      onClick={() =>
                        setAnswers((prev) => ({ ...prev, [item.key]: item.best_guess }))
                      }
                    >
                      采用
                    </button>
                  </p>
                  <label className="field">
                    <span>答复</span>
                    <input
                      className="field__input"
                      value={answers[item.key] ?? ''}
                      onChange={(event) =>
                        setAnswers((prev) => ({ ...prev, [item.key]: event.target.value }))
                      }
                    />
                  </label>
                </li>
              ))}
            </ul>
            <div className="thread__actions">
              <button
                type="button"
                className="button button--primary"
                disabled={isBusy}
                onClick={() => void runFollowup({ answers, escape: false })}
              >
                提交答复
              </button>
              <button
                type="button"
                className="button button--ghost"
                disabled={isBusy}
                onClick={() => void runFollowup({ escape: true })}
              >
                直接生成（A 保守版 + 待确认清单）
              </button>
            </div>
          </div>
        ) : null}

        {view === 'result' ? (
          <div>
            {message !== '' ? <p className="thread__message">{message}</p> : null}
            {ranking !== null ? (
              <div className="ranking-block">
                {ranking.marked ? (
                  <p className="ranking-block__marked">
                    【推荐】{ranking.variant}（置信度 {ranking.confidence}）
                  </p>
                ) : (
                  <p className="ranking-block__reason">{ranking.reason}</p>
                )}
              </div>
            ) : null}
            <ul className="variant-list">
              {variants.map((variant) => (
                <li className="variant-card" key={variant.level}>
                  <h3>
                    {variant.title} <span className="variant-card__level">{variant.level}</span>
                  </h3>
                  {(variant.changes ?? []).length > 0 ? (
                    <ul className="variant-card__changes">
                      {(variant.changes ?? []).map((change) => (
                        <li key={change}>{change}</li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
            <div className="thread__actions">
              {(['A', 'B', 'C'] as const).map((level) => (
                <button
                  key={level}
                  type="button"
                  className="button button--primary"
                  disabled={isBusy}
                  onClick={() => void handleFeedback(level)}
                >
                  采纳 {level}
                </button>
              ))}
              <button
                type="button"
                className="button button--ghost"
                disabled={isBusy}
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
  )
}
