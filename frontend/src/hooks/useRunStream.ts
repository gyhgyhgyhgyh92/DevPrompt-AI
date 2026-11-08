import { useEffect, useRef } from 'react'
import { openSessionStream } from '../api/endpoints'
import type { FlowSnapshotResponse } from '../api/types'
import { isTerminalEvent, type RunEvent } from '../api/protocol'
import { FlowSnapshotSchema } from '../schemas/optimize'
import { useOptimizeStore } from '../stores/useOptimizeStore'

/** 重连退避：显式指数退避，最多 3 次（MUST-15：断流不自动无限重连）。 */
const RECONNECT_DELAYS_MS = [500, 1500, 4000]

/**
 * 订阅会话事件流（GET /sessions/{id}/stream?since=N）。
 *
 * `initialSince` 是**启动本次 run 之前**的会话最大 seq：只消费它之后的事件，
 * 既不会漏掉 run 启动后、订阅建立前的早期事件，也不会把旧轮次重放成重复时间线。
 * 之后按 `seq` 去重、断线按退避从上次 seq 续读、收到 stop/error 主动关闭。
 */
export function useRunStream(
  sessionId: string | null,
  enabled: boolean,
  initialSince = 0,
  onSnapshot?: (snapshot: FlowSnapshotResponse) => void,
): void {
  const sinceRef = useRef(initialSince)
  const attemptRef = useRef(0)
  const snapshotRef = useRef(onSnapshot)

  useEffect(() => {
    snapshotRef.current = onSnapshot
  }, [onSnapshot])

  useEffect(() => {
    sinceRef.current = initialSince
    attemptRef.current = 0
  }, [sessionId, initialSince])

  useEffect(() => {
    if (!sessionId || !enabled) return undefined

    let closed = false
    let timer: number | null = null
    let close: (() => void) | null = null

    const apply = (event: RunEvent): void => {
      // seq=0 是建连合成快照（只含 run/pending 摘要），不参与时间线。
      if (event.seq === 0) return
      if (event.seq <= sinceRef.current) return
      sinceRef.current = event.seq
      if (event.type === 'snapshot') {
        const parsed = FlowSnapshotSchema.safeParse(event.data)
        if (parsed.success) snapshotRef.current?.(parsed.data)
      }
      useOptimizeStore.getState().applyRunEvent(event)
      if (isTerminalEvent(event)) {
        closed = true
        close?.()
      }
    }

    const connect = (): void => {
      close = openSessionStream(sessionId, sinceRef.current, {
        onOpen: () => {
          attemptRef.current = 0
          useOptimizeStore.getState().setSseStatus('open')
        },
        onEvent: apply,
        onError: () => {
          if (closed) return
          useOptimizeStore.getState().setSseStatus('error')
          const delay = RECONNECT_DELAYS_MS[attemptRef.current]
          if (delay === undefined) return
          attemptRef.current += 1
          timer = window.setTimeout(connect, delay)
        },
      })
    }

    connect()
    return () => {
      closed = true
      if (timer !== null) window.clearTimeout(timer)
      close?.()
      useOptimizeStore.getState().setSseStatus('idle')
    }
  }, [sessionId, enabled])
}
