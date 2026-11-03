import { useEffect, useRef, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import type { FollowupRequest } from '../api/types'
import {
  getHistory,
  getResult,
  getSessionTurns,
  getTurn,
  streamFollowup,
  streamOptimize,
} from '../api/endpoints'
import { ChatStream } from '../components/optimize/ChatStream'
import { ConsoleInput } from '../components/optimize/ConsoleInput'
import { TurnList } from '../components/optimize/TurnList'
import { errorMessage } from '../components/settings/errorMessage'
import { useSSE } from '../hooks/useSSE'
import { useOptimizeStore } from '../stores/useOptimizeStore'
import { useHistoryStore } from '../stores/useHistoryStore'

type FlowView = 'input' | 'thinking' | 'asking' | 'result'

/** 距底部多少像素内视为「贴底」：在此范围内新内容自动跟随，超出则视为用户正在回看历史。 */
const THREAD_BOTTOM_GAP = 80

/** 视图选择（仅按后端 status 镜像渲染；状态转移逻辑唯一在后端，MUST-07）。 */
function resolveFlowView(status: string | null): Exclude<FlowView, 'thinking'> {
  if (status === null) return 'input'
  if (status === 'done' || status === 'aborted') return 'result'
  return 'asking'
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
    isSubmitting,
    thinking,
    isThinking,
    turns,
    currentTurnId,
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
      isSubmitting: s.isSubmitting,
      turns: s.turns,
      currentTurnId: s.currentTurnId,
      thinking: s.thinking,
      isThinking: s.isThinking,
    })),
  )

  const [sentence, setSentence] = useState('')
  const [project, setProject] = useState('')
  const [isBusy, setIsBusy] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [elapsedSeconds, setElapsedSeconds] = useState<number | null>(null)
  const streamRef = useRef<AbortController | null>(null)
  const threadRef = useRef<HTMLDivElement | null>(null)
  // 贴底跟随标志：用户上滚后不再把视口拽回底部（对齐 Codex 的线程滚动行为）
  const isStickToBottomRef = useRef(true)

  useSSE(sessionId)

  /** 记录用户是否仍在底部附近（滚动容器唯一来源是对话流，状态不上提，MUST-16）。 */
  function handleThreadScroll(): void {
    const node = threadRef.current
    if (node === null) return
    isStickToBottomRef.current =
      node.scrollHeight - node.scrollTop - node.clientHeight < THREAD_BOTTOM_GAP
  }

  // 内容增量（思考帧、轮次、每轮状态、方案）：仅在贴底时跟随
  useEffect(() => {
    const node = threadRef.current
    if (node === null || !isStickToBottomRef.current) return
    node.scrollTop = node.scrollHeight
  }, [thinking, turns, status, message, questions, variants, isThinking])

  // 进入或切换会话：重置贴底并直接落到底（换会话不该停在上一段的滚动位置）
  useEffect(() => {
    isStickToBottomRef.current = true
    const node = threadRef.current
    if (node === null) return
    node.scrollTop = node.scrollHeight
  }, [sessionId])

  // 多轮历史（切片 2）：会话确定后拉一次轮次摘要；正文由 TurnList 展开时懒加载
  const setTurns = useOptimizeStore((s) => s.setTurns)
  useEffect(() => {
    if (sessionId === null) {
      setTurns([])
      return undefined
    }
    let cancelled = false
    void getSessionTurns(sessionId)
      .then((items) => {
        if (!cancelled) setTurns(items)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [sessionId, setTurns])

  // 卸载即中止在途流（MUST-15：不重连；后端据此把会话置 ABORTED）
  useEffect(() => () => streamRef.current?.abort(), [])

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

  /**
   * 答复 / 逃生 / 护栏裁决：走流式端点（2026-11-03）。
   *
   * 此前用非流式 POST /followup：回答后界面停在上一次快照的 ASKING，看不到重新研判、
   * 生成、评估过程。改流式后服务端逐帧推 thought/action，前端按 phase 同步阶段高亮。
   */
  async function runFollowup(body: FollowupRequest): Promise<void> {
    const activeSessionId = useOptimizeStore.getState().sessionId
    if (!activeSessionId) return
    const store = useOptimizeStore.getState()
    store.beginReprobe()
    setIsBusy(true)
    setErrorMessage(null)

    const controller = new AbortController()
    streamRef.current = controller
    try {
      await streamFollowup(
        activeSessionId,
        body,
        {
          onThought: (text, phase) => {
            const live = useOptimizeStore.getState()
            live.notePhase(phase)
            live.appendThought(text, phase)
          },
          onAction: (action, phase) => {
            const live = useOptimizeStore.getState()
            live.notePhase(phase)
            live.appendAction(action, phase)
          },
          onSnapshot: (snapshot) => {
            useOptimizeStore.getState().applySnapshot(snapshot)
            void getSessionTurns(snapshot.session_id)
              .then((items) => {
                const live = useOptimizeStore.getState()
                live.setTurns(items)
                live.setCurrentTurnId(items.at(-1)?.turn_id ?? null)
              })
              .catch(() => undefined)
          },
          onError: (error) => setErrorMessage(toMessage(error)),
        },
        controller.signal,
      )
    } catch (error) {
      if (!controller.signal.aborted) setErrorMessage(toMessage(error))
    } finally {
      streamRef.current = null
      useOptimizeStore.getState().endThinking()
      setIsBusy(false)
    }
  }

  /**
   * 提交走流式端点：点击即切思考视图，thought 帧按序累积，终态快照切反问/结果视图。
   * 有副作用端点禁重试（MUST-15），中止由 AbortController 收口。
   */
  async function handleOptimizeSubmit(nextSentence: string, nextProject: string): Promise<void> {
    const store = useOptimizeStore.getState()
    store.setSubmitting(true)
    store.beginThinking()
    setSentence(nextSentence)
    setProject(nextProject)
    setStartedAt(Date.now())
    setElapsedSeconds(0)
    setErrorMessage(null)

    const controller = new AbortController()
    streamRef.current = controller
    // 多轮：带上当前会话 id，后端在同一 session 起新 turn（空则新建会话）
    const activeSessionId = useOptimizeStore.getState().sessionId
    try {
      await streamOptimize(
        { sentence: nextSentence, project: nextProject, session_id: activeSessionId ?? undefined },
        {
          onThought: (text, phase) => useOptimizeStore.getState().appendThought(text, phase),
          onAction: (action, phase) => useOptimizeStore.getState().appendAction(action, phase),
          onSnapshot: (snapshot) => {
            useOptimizeStore.getState().applySnapshot(snapshot)
            void getSessionTurns(snapshot.session_id)
              .then((items) => {
                const store = useOptimizeStore.getState()
                store.setTurns(items)
                store.setCurrentTurnId(items.at(-1)?.turn_id ?? null)
              })
              .catch(() => undefined)
            void getHistory()
              .then((items) => useHistoryStore.getState().setHistory(items))
              .catch(() => undefined)
          },
          onError: (error) => setErrorMessage(toMessage(error)),
        },
        controller.signal,
      )
    } catch (error) {
      // 主动中止（卸载）不提示；其余失败给出降级文案
      if (!controller.signal.aborted) setErrorMessage(toMessage(error))
    } finally {
      streamRef.current = null
      useOptimizeStore.getState().endThinking()
      useOptimizeStore.getState().setSubmitting(false)
    }
  }

  // 思考中优先于一切：提交后立即离开输入页，不等后端返回
  const view: FlowView = isThinking ? 'thinking' : resolveFlowView(status)

  return (
    <div className="optimize-page">
      {view === 'input' ? (
        <div className="optimize-page__center">
          <ConsoleInput
            isSubmitting={isSubmitting || isBusy}
            initialSentence={sentence}
            initialProject={project}
            onSubmit={(nextSentence, nextProject) => {
              void handleOptimizeSubmit(nextSentence, nextProject)
            }}
          />
          {errorMessage !== null ? <p className="thread__error">{errorMessage}</p> : null}
        </div>
      ) : (
        <>
          {/* 对话流滚动区（2026-11-01）：外壳固定视口，只有这里滚动 */}
          <div className="optimize-page__thread" ref={threadRef} onScroll={handleThreadScroll}>
            {/* 历史轮次：最后一条即当前 ChatStream 展示的这轮，故从列表里排除 */}
            <TurnList
              turns={
                currentTurnId === null
                  ? turns
                  : turns.filter((turn) => turn.turn_id !== currentTurnId)
              }
              loadTurn={getTurn}
            />
            <ChatStream
              state={state}
              status={status}
              sentence={sentence}
              thinking={thinking}
              isThinking={isThinking}
              message={message}
              questions={questions}
              cleared={cleared}
              variants={variants}
              ranking={ranking}
              elapsedSeconds={elapsedSeconds}
              errorMessage={errorMessage}
              isBusy={isBusy || isSubmitting}
              onSubmitAnswers={(answers) => void runFollowup({ answers, escape: false })}
              onEscape={() => void runFollowup({ escape: true })}
              onGuardrail={(action) =>
                void runFollowup({ escape: false, guardrail_action: action })
              }
            />
          </div>
          {/* 多轮：输入区常驻，提交即在同一会话追加一轮（思考中不展示，避免误触） */}
          {isThinking ? null : (
            <div className="optimize-page__composer">
              <ConsoleInput
                isSubmitting={isSubmitting || isBusy}
                initialProject={project}
                projectOptional
                onSubmit={(nextSentence, nextProject) => {
                  void handleOptimizeSubmit(nextSentence, nextProject)
                }}
              />
            </div>
          )}
        </>
      )}
    </div>
  )
}
