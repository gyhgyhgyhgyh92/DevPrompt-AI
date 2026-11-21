/**
 * 会话事件流 hook（2026-11-17 抽取）。
 *
 * 为什么抽：Session Log 视图与桌面端底部「运行日志」面板需要同一份实时事件流。
 * seq 去重、内存缓冲上限、SSE 续订起点这三件事若各写一份，迟早漂移
 * （典型后果：桌面面板重复追加同一事件，或绕过缓冲上限无限增长）。
 * 故把「事件数组 + 去重 + 缓冲 + 翻页 + 订阅 + 清理」收敛到本 hook，视图只管渲染。
 *
 * 订阅生命周期：SSE 的 close 由 openSessionStream 的返回值（effect cleanup）承担，
 * 组件卸载或会话切换时自动断开，不自动重连（MUST-15）。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { getSessionEvents, openSessionStream } from '../../api/endpoints'
import type { RunEvent } from '../../api/protocol'

export type SessionEvent = RunEvent

/** 每页事件数（与后端 /events 的默认上限一致）。 */
export const PAGE_LIMIT = 200
/** 实时跟随时内存里最多保留的事件数，防止长时间挂机无限增长。 */
export const LIVE_BUFFER_LIMIT = 2000
/** 首次加载用「极大 seq」取最新一页（后端按 before 倒序分页）。 */
const LATEST_CURSOR = 1 << 30

export interface SessionEventStream {
  /** 事件列表（升序）。 */
  events: readonly SessionEvent[]
  loading: boolean
  /** 是否还有更早的历史页。 */
  hasMore: boolean
  error: string
  /** 是否处于实时跟随。 */
  isLive: boolean
  setIsLive: (live: boolean) => void
  /** 重新拉取最新一页。 */
  reload: () => void
  /** 向前翻一页（更早的事件）。 */
  loadOlder: () => void
}

export function useSessionEventStream(sessionId: string | null): SessionEventStream {
  const [events, setEvents] = useState<SessionEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [error, setError] = useState('')
  const [isLive, setIsLive] = useState(false)
  /**
   * 本页最大 seq：实时订阅的续订起点。
   * 为 null 表示「本页尚未加载完」——此时不订阅，避免用上一会话的 seq 去续订新会话。
   */
  const [loadedSeq, setLoadedSeq] = useState<number | null>(null)
  const eventsRef = useRef<SessionEvent[]>([])

  useEffect(() => {
    eventsRef.current = events
  }, [events])

  const loadLatest = useCallback(async (id: string): Promise<void> => {
    setLoading(true)
    setError('')
    try {
      const page = await getSessionEvents(id, LATEST_CURSOR, PAGE_LIMIT)
      setEvents(page)
      setHasMore(page.length >= PAGE_LIMIT)
      setLoadedSeq(page.at(-1)?.seq ?? 0)
    } catch (err) {
      setError(String(err))
      setLoadedSeq(0)
    } finally {
      setLoading(false)
    }
  }, [])

  // 会话切换：清空旧事件并拉取新会话的最新一页（loadedSeq 先置 null，断开旧订阅）
  useEffect(() => {
    setEvents([])
    setHasMore(false)
    setLoadedSeq(null)
    if (sessionId === null) return
    void loadLatest(sessionId)
  }, [sessionId, loadLatest])

  // 实时跟随：从本页最大 seq 续订，按 seq 去重后追加（连接失败不弹错，保持历史可读）
  useEffect(() => {
    if (!isLive || sessionId === null || loadedSeq === null) return undefined
    return openSessionStream(sessionId, loadedSeq, {
      onEvent: (event) => {
        if (event.seq === 0) return
        setEvents((prev) => {
          if (prev.some((item) => item.seq === event.seq)) return prev
          return [...prev, event].slice(-LIVE_BUFFER_LIMIT)
        })
      },
    })
  }, [isLive, sessionId, loadedSeq])

  const loadOlder = useCallback((): void => {
    if (sessionId === null) return
    const before = eventsRef.current[0]?.seq ?? 0
    if (before <= 0) return
    setLoading(true)
    void getSessionEvents(sessionId, before, PAGE_LIMIT)
      .then((page) => {
        setEvents((prev) => [...page, ...prev])
        setHasMore(page.length >= PAGE_LIMIT)
      })
      .catch((err: unknown) => setError(String(err)))
      .finally(() => setLoading(false))
  }, [sessionId])

  const reload = useCallback((): void => {
    if (sessionId !== null) void loadLatest(sessionId)
  }, [sessionId, loadLatest])

  return { events, loading, hasMore, error, isLive, setIsLive, reload, loadOlder }
}
