import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  compareObsTraces,
  createObsReplay,
  getHistory,
  getObsEvents,
  getObsReplayRun,
  getObsTraces,
} from '../../api/endpoints'
import type { HistoryItemPayload } from '../../api/types'
import { SessionListView } from './SessionListView'
import { ReplayControls } from './ReplayControls'
import { ReplayTimeline } from './ReplayTimeline'
import { makeS } from '../../utils/css'
import styles from './observability.module.css'

const s = makeS(styles)

type Item = Record<string, unknown>
type Node = Record<string, unknown>

/** Replay 模块：verify（单 Trace 确定性回归）与 compare（双 Trace 版本对比）。 */
export function ReplayPanel() {
  const { t } = useTranslation()
  const [sessions, setSessions] = useState<HistoryItemPayload[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [traces, setTraces] = useState<Item[]>([])
  const [left, setLeft] = useState('')
  const [right, setRight] = useState('')
  const [nodes, setNodes] = useState<Node[]>([])
  const [status, setStatus] = useState('')
  const [final, setFinal] = useState<Record<string, unknown>>({})
  const [error, setError] = useState('')
  const [cursor, setCursor] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [points, setPoints] = useState<
    Array<{
      seq: number
      type: string
      ts: string
      run_id: string
      label: string
      phase: string
      duration_ms: number | null
    }>
  >([])

  useEffect(() => {
    let alive = true
    getHistory({ limit: 50 })
      .then((page) => {
        if (!alive) return
        setSessions(page.items)
        setSessionId((prev) => prev ?? page.items[0]?.session_id ?? null)
      })
      .catch((err: unknown) => alive && setError(String(err)))
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    if (sessionId === null) return
    let alive = true
    setTraces([])
    setLeft('')
    setRight('')
    setNodes([])
    setFinal({})
    setStatus('')
    Promise.all([getObsTraces(sessionId), getObsEvents(sessionId, { limit: 500 })])
      .then(([tracePage, eventPage]) => {
        if (!alive) return
        setTraces(tracePage.items)
        const first = String(tracePage.items[0]?.trace_id ?? '')
        setLeft(first)
        setRight(String(tracePage.items[1]?.trace_id ?? first))
        setPoints(
          eventPage.items.map((item) => ({
            seq: Number(item.seq ?? 0),
            type: String(item.kind ?? ''),
            ts: String(item.started_at ?? ''),
            run_id: String(item.run_id ?? ''),
            label: String(item.name ?? ''),
            phase: '',
            duration_ms: Number(item.duration_ms ?? 0),
          })),
        )
      })
      .catch((err: unknown) => alive && setError(String(err)))
    return () => {
      alive = false
    }
  }, [sessionId])

  useEffect(() => {
    if (!playing || points.length === 0) return undefined
    const timer = window.setInterval(() => {
      setCursor((prev) => {
        if (prev >= points.length - 1) {
          setPlaying(false)
          return prev
        }
        return prev + 1
      })
    }, 500 / speed)
    return () => window.clearInterval(timer)
  }, [playing, speed, points.length])

  const current = points[Math.min(cursor, Math.max(0, points.length - 1))]
  const mismatch = useMemo(() => nodes.filter((node) => node.match !== true).length, [nodes])

  const runVerify = async (): Promise<void> => {
    setError('')
    setNodes([])
    setFinal({})
    setStatus('running')
    try {
      const created = await createObsReplay({ mode: 'verify', left_trace_id: left })
      const runId = String(created.run.run_id ?? '')
      for (let attempt = 0; attempt < 60; attempt += 1) {
        const latest = await getObsReplayRun(runId)
        const state = String(latest.run.status ?? '')
        if (state !== 'running') {
          setStatus(state)
          setNodes(latest.nodes)
          setFinal((latest.run.result as Record<string, unknown>) ?? {})
          return
        }
        await new Promise((resolve) => window.setTimeout(resolve, 500))
      }
      setStatus('timeout')
    } catch (err) {
      setError(String(err))
      setStatus('failed')
    }
  }

  const runCompare = async (): Promise<void> => {
    setError('')
    setStatus('running')
    try {
      const result = await compareObsTraces(left, right)
      setNodes(result.nodes)
      setFinal(result.final)
      setStatus('matched')
    } catch (err) {
      setError(String(err))
      setStatus('failed')
    }
  }

  return (
    <div className={s('obs-layout')}>
      <SessionListView
        sessions={sessions}
        selectedId={sessionId}
        loading={false}
        error=""
        hasMore={false}
        onSelect={setSessionId}
        onLoadMore={() => undefined}
      />
      <div className={s('obs-main')}>
        <section className={s('obs-replay')}>
          <div className={s('obs-toolbar')}>
            <div className={s('obs-toolbar__row')}>
              <select
                className={s('obs-select')}
                aria-label="left trace"
                value={left}
                onChange={(event) => setLeft(event.currentTarget.value)}
              >
                {traces.map((item) => (
                  <option key={String(item.trace_id)} value={String(item.trace_id)}>
                    #{String(item.turn_index)} {String(item.status)} · {String(item.trace_id)}
                  </option>
                ))}
              </select>
              <select
                className={s('obs-select')}
                aria-label="right trace"
                value={right}
                onChange={(event) => setRight(event.currentTarget.value)}
              >
                {traces.map((item) => (
                  <option key={String(item.trace_id)} value={String(item.trace_id)}>
                    #{String(item.turn_index)} {String(item.status)} · {String(item.trace_id)}
                  </option>
                ))}
              </select>
              <button type="button" className={s('obs-button')} onClick={() => void runVerify()}>
                {t('observability.replay.play')} Verify
              </button>
              <button
                type="button"
                className={s('obs-button obs-button--ghost')}
                onClick={() => void runCompare()}
              >
                Compare
              </button>
              <span className={s('obs-note')}>
                {status !== '' ? `status: ${status}` : ''} · mismatch: {mismatch}
              </span>
            </div>
          </div>
          {error !== '' ? <p className={s('obs-status obs-status--error')}>{error}</p> : null}
          <div className={s('obs-card')}>
            <ReplayTimeline
              points={points}
              cursor={Math.min(cursor, Math.max(0, points.length - 1))}
              range={null}
              onSeek={(index) => {
                setPlaying(false)
                setCursor(index)
              }}
              onRangeChange={() => undefined}
            />
            <ReplayControls
              cursor={Math.min(cursor, Math.max(0, points.length - 1))}
              total={points.length}
              playing={playing}
              speed={speed}
              onToggle={() => setPlaying((prev) => !prev)}
              onRestart={() => {
                setPlaying(false)
                setCursor(0)
              }}
              onStep={(delta) =>
                setCursor((prev) => Math.max(0, Math.min(points.length - 1, prev + delta)))
              }
              onSpeedChange={setSpeed}
            />
            {current !== undefined ? (
              <div className={s('obs-cursor-card')}>
                <strong>
                  #{current.seq} · {current.type} · {current.label}
                </strong>
                <span>{current.ts}</span>
              </div>
            ) : null}
          </div>
          <div className={s('obs-card')}>
            <h4 className={s('obs-card__title')}>{t('observability.inspector.title')}</h4>
            {nodes.length === 0 ? (
              <p className={s('obs-empty')}>{t('observability.metrics.no_data')}</p>
            ) : (
              <ul className={s('obs-bars')}>
                {nodes.map((node) => (
                  <li key={`${String(node.seq)}-${String(node.name)}`} className={s('obs-bar')}>
                    <span className={s('obs-bar__label')}>
                      #{String(node.seq)} {String(node.kind)} {String(node.name)}
                    </span>
                    <span className={s('obs-bar__track')}>
                      <span
                        className={s('obs-bar__fill')}
                        style={{ width: node.match === true ? '100%' : '35%' }}
                      />
                    </span>
                    <span className={s('obs-bar__value')}>
                      {node.match === true ? 'MATCH' : 'DIFF'}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          {Object.keys(final).length > 0 ? (
            <div className={s('obs-card')}>
              <h4 className={s('obs-card__title')}>final snapshot diff</h4>
              <pre className={s('obs-inspector__raw')}>{JSON.stringify(final, null, 2)}</pre>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  )
}
