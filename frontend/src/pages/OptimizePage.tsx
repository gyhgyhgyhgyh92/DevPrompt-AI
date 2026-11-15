import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useShallow } from 'zustand/react/shallow'
import type { FollowupRequest } from '../api/types'
import {
  HISTORY_PAGE_SIZE,
  TURNS_PAGE_SIZE,
  cancelRun,
  fetchLastSeq,
  getHistory,
  getResult,
  getSessionTurns,
  getTurn,
  rollbackSession,
  startRun,
  streamFollowup,
  streamOptimize,
} from '../api/endpoints'
import { AgentTimeline } from '../components/optimize/AgentTimeline'
import { EvidenceStaleNotice } from '../components/optimize/EvidenceStaleNotice'
import { ChatStream } from '../components/optimize/ChatStream'
import { ConsoleInput } from '../components/optimize/ConsoleInput'
import { DomainSelect } from '../components/optimize/DomainSelect'
import { TurnList } from '../components/optimize/TurnList'
import { errorMessage } from '../components/settings/errorMessage'
import { i18n } from '../i18n'
import { useSSE } from '../hooks/useSSE'
import { useRunStream } from '../hooks/useRunStream'
import { useOptimizeStore } from '../stores/useOptimizeStore'
import { useHistoryStore } from '../stores/useHistoryStore'
import { MAX_IMAGES, MAX_IMAGE_BYTES, type DomainId, type VisualStyle } from '../schemas/optimize'
import { makeS } from '../utils/css'
import chatStyles from '../components/optimize/ChatStream.module.css'
import styles from './OptimizePage.module.css'

// 页面层与对话层共用少量类（thread__error），合并两张类名表
const s = makeS({ ...chatStyles, ...styles })

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
  return errorMessage(error, i18n.t('common.request_failed'))
}

/** 视觉风格下拉选项（general 为缺省空值，不在列表中重复出现）。 */
const VISUAL_STYLE_OPTIONS: VisualStyle[] = [
  'photography',
  'creative',
  'chinese-model',
  'json-structured',
  'video',
]

/** 模式/风格选择跨会话记忆键（图片 data URL 不落盘）。 */
const DOMAIN_MEMORY_KEY = 'devprompt.domainOverride'
const STYLE_MEMORY_KEY = 'devprompt.visualStyle'

/** 读 localStorage 字符串；存储内容不可信，由 useState 缺省值兜底。 */
function storedOrEmpty(key: string): string {
  return window.localStorage.getItem(key) ?? ''
}

/** 优化主页（设计文档 §1.1 对话流：无会话时居中输入卡片，有会话时图五对话流）。 */
export function OptimizePage() {
  const { t } = useTranslation()
  const {
    sessionId,
    state,
    status,
    message,
    questions,
    cleared,
    variant,
    isSubmitting,
    thinking,
    isThinking,
    turns,
    hasMoreTurns,
    currentTurnId,
    agentStep,
    agentAction,
    agentElapsedMs,
    evidenceStale,
    replyText,
    deliveryGate,
    domain: domainVerdict,
  } = useOptimizeStore(
    useShallow((s) => ({
      sessionId: s.sessionId,
      state: s.state,
      status: s.status,
      message: s.message,
      questions: s.questions,
      cleared: s.cleared,
      variant: s.variant,
      isSubmitting: s.isSubmitting,
      turns: s.turns,
      hasMoreTurns: s.hasMoreTurns,
      currentTurnId: s.currentTurnId,
      agentStep: s.agentStep,
      agentAction: s.agentAction,
      agentElapsedMs: s.agentElapsedMs,
      evidenceStale: s.evidenceStale,
      replyText: s.replyText,
      deliveryGate: s.deliveryGate,
      domain: s.domain,
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
  // 模式选择（2026-11-14 多模态）：空串 = 自动路由；选 visual 联动风格与参考图上传。
  const [domainOverride, setDomainOverride] = useState<'' | DomainId>(
    () => storedOrEmpty(DOMAIN_MEMORY_KEY) as '' | DomainId,
  )
  const [visualStyle, setVisualStyle] = useState<'' | VisualStyle>(
    () => storedOrEmpty(STYLE_MEMORY_KEY) as '' | VisualStyle,
  )
  const [images, setImages] = useState<{ name: string; dataUrl: string }[]>([])
  const [imageError, setImageError] = useState<string | null>(null)
  const imageInputRef = useRef<HTMLInputElement | null>(null)
  const streamRef = useRef<AbortController | null>(null)
  const runIdRef = useRef<string | null>(null)
  const [runSessionId, setRunSessionId] = useState<string | null>(null)
  const [streamSince, setStreamSince] = useState(0)
  const threadRef = useRef<HTMLDivElement | null>(null)
  // 贴底跟随标志：用户上滚后不再把视口拽回底部（对齐 Codex 的线程滚动行为）
  const isStickToBottomRef = useRef(true)

  useSSE(sessionId)

  // 模式/风格切换：选择即持久化（空串 = 清除记忆，回到自动路由）
  function handleDomainSwitch(value: string): void {
    setDomainOverride(value as '' | DomainId)
    if (value === '') window.localStorage.removeItem(DOMAIN_MEMORY_KEY)
    else window.localStorage.setItem(DOMAIN_MEMORY_KEY, value)
  }

  function handleVisualStyleChange(value: string): void {
    setVisualStyle(value as '' | VisualStyle)
    if (value === '') window.localStorage.removeItem(STYLE_MEMORY_KEY)
    else window.localStorage.setItem(STYLE_MEMORY_KEY, value)
  }

  function fileToDataUrl(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result))
      reader.onerror = () => reject(reader.error)
      reader.readAsDataURL(file)
    })
  }

  /** 参考图挑选：逐张校验数量/格式/体积（与后端 validate_images 对齐），行内提示不弹窗。 */
  async function handleImagePick(fileList: FileList | null): Promise<void> {
    if (fileList === null || fileList.length === 0) return
    setImageError(null)
    const accepted: { name: string; dataUrl: string }[] = [...images]
    let error: string | null = null
    for (const file of Array.from(fileList)) {
      if (accepted.length >= MAX_IMAGES) {
        error = t('optimize.image_limit', { max: MAX_IMAGES })
        break
      }
      if (file.type !== 'image/png' && file.type !== 'image/jpeg' && file.type !== 'image/webp') {
        error = t('optimize.image_format')
        continue
      }
      if (file.size > MAX_IMAGE_BYTES) {
        error = t('optimize.image_size')
        continue
      }
      const dataUrl = await fileToDataUrl(file).catch((err: unknown) => {
        console.error(err)
        return ''
      })
      if (dataUrl === '') {
        error = t('optimize.image_read_failed')
        continue
      }
      accepted.push({ name: file.name, dataUrl })
    }
    setImages(accepted)
    if (error !== null) setImageError(error)
  }

  // 多端协议：订阅本次 run 的会话事件流；快照到达后刷新轮次与历史列表。
  useRunStream(runSessionId, isThinking, streamSince, (snapshot) => {
    void getSessionTurns(snapshot.session_id, { limit: TURNS_PAGE_SIZE })
      .then((page) => {
        const store = useOptimizeStore.getState()
        store.setTurns(page.items, page.has_more)
        store.setCurrentTurnId(snapshot.current_turn_id ?? page.items.at(-1)?.turn_id ?? null)
      })
      .catch(() => undefined)
    void getHistory({ limit: HISTORY_PAGE_SIZE })
      .then((page) => useHistoryStore.getState().setHistory(page.items, page.has_more))
      .catch(() => undefined)
  })

  /** 记录用户是否仍在底部附近（滚动容器唯一来源是对话流，状态不上提，MUST-16）。 */
  function handleThreadScroll(): void {
    const node = threadRef.current
    if (node === null) return
    isStickToBottomRef.current =
      node.scrollHeight - node.scrollTop - node.clientHeight < THREAD_BOTTOM_GAP
  }

  // 内容增量（思考帧、轮次、每轮状态、方案）：仅在贴底时跟随。
  // 打字机每秒推进数十帧，这里把多次 store 变更合并到同一帧，避免逐字抖动与重复写 scrollTop。
  const scrollFrameRef = useRef<number | null>(null)
  useEffect(() => {
    const flush = (): void => {
      scrollFrameRef.current = null
      const node = threadRef.current
      if (node === null || !isStickToBottomRef.current) return
      node.scrollTop = node.scrollHeight
    }
    if (typeof requestAnimationFrame !== 'function') {
      flush()
      return
    }
    // 已有排队帧则不再重复排队（一帧一次足够）
    scrollFrameRef.current ??= requestAnimationFrame(flush)
  }, [thinking, turns, status, message, questions, variant, isThinking])

  useEffect(
    () => () => {
      if (scrollFrameRef.current !== null) cancelAnimationFrame(scrollFrameRef.current)
    },
    [],
  )

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
    void getSessionTurns(sessionId, { limit: TURNS_PAGE_SIZE })
      .then((page) => {
        if (cancelled) return
        setTurns(page.items, page.has_more)
        // 归属兜底（2026-11-04）：刷新/切会话时「谁进历史列表、谁是当前轮」要有确定值，
        // 否则 TurnList 与 ChatStream 会把最后一轮各渲染一次。仅当当前没有归属、或归属不在
        // 本会话列表里（切了会话），且不在流式思考中（否则会顶掉刚提交新轮时置的 null）。
        const store = useOptimizeStore.getState()
        if (store.isThinking) return
        const belongs = page.items.some((item) => item.turn_id === store.currentTurnId)
        if (!belongs && page.items.length > 0) {
          store.setCurrentTurnId(page.items.at(-1)?.turn_id ?? null)
        }
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [sessionId, setTurns])

  // 「加载更早的轮次」：服务端按 offset 从最新往回数，取回后与已有摘要合并
  const [loadingEarlier, setLoadingEarlier] = useState(false)
  const loadEarlierTurns = useCallback(async () => {
    const store = useOptimizeStore.getState()
    if (store.sessionId === null || !store.hasMoreTurns) return
    setLoadingEarlier(true)
    try {
      const page = await getSessionTurns(store.sessionId, {
        limit: TURNS_PAGE_SIZE,
        offset: store.turns.length,
      })
      store.appendTurns(page.items, page.has_more)
    } catch {
      // 加载失败保持原样：用户可再次点击重试（不自动重试，MUST-15）
    } finally {
      setLoadingEarlier(false)
    }
  }, [])

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
            void getSessionTurns(snapshot.session_id, { limit: TURNS_PAGE_SIZE })
              .then((page) => {
                const live = useOptimizeStore.getState()
                live.setTurns(page.items, page.has_more)
                // 归属优先用快照给出的本轮 id（2026-11-04）：列表可能还没包含这一轮，
                // 若退回「末位推断」会把刚产出的这一轮又标成历史轮。
                live.setCurrentTurnId(
                  snapshot.current_turn_id ?? page.items.at(-1)?.turn_id ?? null,
                )
              })
              .catch(() => undefined)
            void getHistory({ limit: HISTORY_PAGE_SIZE })
              .then((page) => useHistoryStore.getState().setHistory(page.items, page.has_more))
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

  /** 撤销到某一轮（物理删除其后轮次）：以服务端快照为准重建本地镜像，列表全量重拉。 */
  async function handleRollbackTo(turnId: string): Promise<void> {
    const activeSessionId = useOptimizeStore.getState().sessionId
    if (!activeSessionId) return
    setIsBusy(true)
    setErrorMessage(null)
    try {
      const snapshot = await rollbackSession(activeSessionId, turnId)
      useOptimizeStore.getState().applySnapshot(snapshot)
      // 撤销后没有「当前轮」：历史列表全量展示（最新一轮就是基线轮本身）
      useOptimizeStore.getState().setCurrentTurnId(null)
      const page = await getSessionTurns(activeSessionId, { limit: TURNS_PAGE_SIZE })
      useOptimizeStore.getState().setTurns(page.items, page.has_more)
      void getHistory({ limit: HISTORY_PAGE_SIZE })
        .then((page) => useHistoryStore.getState().setHistory(page.items, page.has_more))
        .catch(() => undefined)
    } catch (error) {
      setErrorMessage(toMessage(error))
    } finally {
      setIsBusy(false)
    }
  }

  /**
   * 提交走流式端点：点击即切思考视图，thought 帧按序累积，终态快照切反问/结果视图。
   * 有副作用端点禁重试（MUST-15），中止由 AbortController 收口。
   */
  async function handleOptimizeSubmit(
    nextSentence: string,
    nextProject: string,
    baseTurnId = '',
  ): Promise<void> {
    const store = useOptimizeStore.getState()
    store.setSubmitting(true)
    store.beginThinking()
    setSentence(nextSentence)
    setProject(nextProject)
    setStartedAt(Date.now())
    setElapsedSeconds(0)
    setErrorMessage(null)

    // 多端协议（2026-11-07）：先取起始 seq → 起 run → 订阅事件流。
    // 执行在服务端独立进行，连接关闭不会中断；重连用 since 只补差。
    const activeSessionId = useOptimizeStore.getState().sessionId
    const sessionId = activeSessionId ?? crypto.randomUUID()
    let started = false
    try {
      const since = activeSessionId ? await fetchLastSeq(sessionId) : 0
      const record = await startRun({
        session_id: sessionId,
        project: nextProject,
        sentence: nextSentence,
        base_turn_id: baseTurnId,
        // 领域恒自动路由（2026-11-14 用户裁定：前端无手动入口）
        domain: undefined,
      })
      started = true
      runIdRef.current = record.run_id
      setStreamSince(since)
      setRunSessionId(sessionId)
      useOptimizeStore.getState().setSubmitting(false)
    } catch (error) {
      // run 已启动就不能回退（否则会重复执行）；只有启动前失败才走旧流。
      if (started) {
        setErrorMessage(toMessage(error))
        useOptimizeStore.getState().endThinking()
        useOptimizeStore.getState().setSubmitting(false)
        return
      }
      // 运行时协议不可用（旧后端 / 契约不匹配）→ 回退旧流式端点。
      // 这是灰度期的安全网：新协议是主路径，回退不是常态。
      await runLegacyStream(nextSentence, nextProject, baseTurnId)
    }
  }

  /** 旧流式端点回退（POST /optimize/stream），与改造前行为一致。 */
  async function runLegacyStream(
    nextSentence: string,
    nextProject: string,
    baseTurnId: string,
  ): Promise<void> {
    const controller = new AbortController()
    streamRef.current = controller
    const activeSessionId = useOptimizeStore.getState().sessionId
    try {
      await streamOptimize(
        {
          sentence: nextSentence,
          project: nextProject,
          session_id: activeSessionId ?? undefined,
          base_turn_id: baseTurnId,
          // 模式选择（2026-11-14 多模态）：空串 = 自动路由；选 visual 附风格与参考图
          domain: domainOverride === '' ? undefined : domainOverride,
          style: domainOverride === 'visual' && visualStyle !== '' ? visualStyle : undefined,
          images:
            domainOverride === 'visual' && images.length > 0
              ? images.map((img) => img.dataUrl)
              : undefined,
        },
        {
          onThought: (text, phase) => useOptimizeStore.getState().appendThought(text, phase),
          onAction: (action, phase) => useOptimizeStore.getState().appendAction(action, phase),
          onSnapshot: (snapshot) => {
            useOptimizeStore.getState().applySnapshot(snapshot)
            void getSessionTurns(snapshot.session_id, { limit: TURNS_PAGE_SIZE })
              .then((page) => {
                const store = useOptimizeStore.getState()
                store.setTurns(page.items, page.has_more)
                store.setCurrentTurnId(
                  snapshot.current_turn_id ?? page.items.at(-1)?.turn_id ?? null,
                )
              })
              .catch(() => undefined)
            void getHistory({ limit: HISTORY_PAGE_SIZE })
              .then((page) => useHistoryStore.getState().setHistory(page.items, page.has_more))
              .catch(() => undefined)
          },
          onError: (streamError) => setErrorMessage(toMessage(streamError)),
        },
        controller.signal,
      )
    } catch (streamError) {
      if (!controller.signal.aborted) setErrorMessage(toMessage(streamError))
    } finally {
      streamRef.current = null
      useOptimizeStore.getState().endThinking()
      useOptimizeStore.getState().setSubmitting(false)
    }
  }

  /** 模式选择 + 视觉联动行：hero 输入视图与对话流 composer 共用同一份 state（2026-11-14 多模态）。 */
  function renderModeControls() {
    return (
      <>
        <label className={s('optimize-page__model-switch')}>
          <span>{t('optimize.domain_switch')}</span>
          <DomainSelect
            value={domainOverride}
            disabled={isThinking}
            onChange={(next) => handleDomainSwitch(next)}
          />
        </label>
        {domainOverride === 'visual' ? (
          <div className={s('optimize-page__visual-row')}>
            <label className={s('optimize-page__model-switch optimize-page__style-switch')}>
              <span>{t('optimize.style_switch')}</span>
              <select
                value={visualStyle}
                disabled={isThinking}
                onChange={(e) => handleVisualStyleChange(e.target.value)}
              >
                <option value="">{t('optimize.style_general')}</option>
                {VISUAL_STYLE_OPTIONS.map((style) => (
                  <option key={style} value={style}>
                    {t(`optimize.style_${style.replace(/-/g, '_')}`)}
                  </option>
                ))}
              </select>
            </label>
            <input
              ref={imageInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              multiple
              hidden
              onChange={(e) => {
                void handleImagePick(e.target.files)
                e.target.value = ''
              }}
            />
            <button
              type="button"
              className={s('optimize-page__image-add')}
              disabled={isThinking}
              onClick={() => imageInputRef.current?.click()}
            >
              {t('optimize.image_add')}
            </button>
            {imageError !== null ? (
              <span className={s('optimize-page__image-error')}>{imageError}</span>
            ) : null}
            {images.length > 0 ? (
              <div className={s('optimize-page__images')}>
                {images.map((img, index) => (
                  <span key={`${img.name}-${index}`} className={s('optimize-page__image-chip')}>
                    <img src={img.dataUrl} alt={img.name} />
                    <button
                      type="button"
                      aria-label={t('optimize.image_remove')}
                      disabled={isThinking}
                      onClick={() => setImages((prev) => prev.filter((_, i) => i !== index))}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </>
    )
  }

  // 思考中优先于一切：提交后立即离开输入页，不等后端返回
  const view: FlowView = isThinking ? 'thinking' : resolveFlowView(status)

  return (
    <div className={s('optimize-page')}>
      {view === 'input' ? (
        <div className={s('optimize-page__center')}>
          <ConsoleInput
            isSubmitting={isSubmitting || isBusy}
            initialSentence={sentence}
            initialProject={project}
            isHero
            modeControls={renderModeControls()}
            onSubmit={(nextSentence, nextProject) => {
              void handleOptimizeSubmit(nextSentence, nextProject)
            }}
          />
          {errorMessage !== null ? <p className={s('thread__error')}>{errorMessage}</p> : null}
        </div>
      ) : (
        <>
          {/* 对话流滚动区（2026-11-01）：外壳固定视口，只有这里滚动 */}
          <div className={s('optimize-page__thread')} ref={threadRef} onScroll={handleThreadScroll}>
            {/* 历史轮次：最后一条即当前 ChatStream 展示的这轮，故从列表里排除 */}
            <TurnList
              turns={
                currentTurnId === null
                  ? turns
                  : turns.filter((turn) => turn.turn_id !== currentTurnId)
              }
              loadTurn={getTurn}
              hasMore={hasMoreTurns}
              onLoadEarlier={() => void loadEarlierTurns()}
              loadingEarlier={loadingEarlier}
              onContinueFrom={(turnId) => {
                // 以该历史轮为基线新开一轮：原句留空（后端沿用上一轮目标），历史轮一条不少
                void handleOptimizeSubmit('', project, turnId)
              }}
              onRollbackTo={(turnId) => void handleRollbackTo(turnId)}
            />
            {/* agentic 循环进度：仅在 running 快照期间出现，让用户看到这一步在做什么 */}
            <AgentTimeline step={agentStep} action={agentAction} elapsedMs={agentElapsedMs} />
            {/* 交付时证据已过期：代码被改过，方案引用的行号可能失效（只披露不阻断） */}
            <EvidenceStaleNotice stale={evidenceStale} />
            <ChatStream
              state={state}
              status={status}
              sentence={sentence}
              thinking={thinking}
              isThinking={isThinking}
              message={message}
              replyText={replyText}
              questions={questions}
              cleared={cleared}
              variant={variant}
              deliveryGate={deliveryGate}
              domainVerdict={domainVerdict}
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
          {/* 多轮：输入区常驻，提交即在同一会话追加一轮。
              思考中不再整块隐藏（2026-11-05 形态层）：改为禁用输入 + 显式「停止生成」，
              用户可随时中断当前轮（后端 CancelledError → ABORTED）。 */}
          <div className={s('optimize-page__composer')}>
            <ConsoleInput
              isSubmitting={isSubmitting || isBusy}
              initialProject={project}
              projectOptional
              disabled={isThinking}
              modeControls={renderModeControls()}
              onSubmit={(nextSentence, nextProject) => {
                void handleOptimizeSubmit(nextSentence, nextProject)
              }}
            />
            {isThinking ? (
              <button
                type="button"
                className={s('button button--ghost optimize-page__stop')}
                onClick={() => {
                  const runId = runIdRef.current
                  if (runId !== null) void cancelRun(runId).catch(() => undefined)
                  else streamRef.current?.abort()
                  // 中断后以服务端为准校对（验收⑤）：后端 CancelledError → ABORTED；
                  // 若取消尚未到达后端（仍 running），快照刷新会把界面拉回真实状态，不伪造。
                  const sid = useOptimizeStore.getState().sessionId
                  if (sid) {
                    window.setTimeout(() => {
                      void getResult(sid)
                        .then((snapshot) => useOptimizeStore.getState().applySnapshot(snapshot))
                        .catch(() => undefined)
                    }, 800)
                  }
                }}
              >
                {t('optimize.stop_generation')}
              </button>
            ) : null}
          </div>
        </>
      )}
    </div>
  )
}
