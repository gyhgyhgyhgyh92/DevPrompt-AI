import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getHistory, getSessionEvents, openSessionStream } from '../../api/endpoints'
import type { RunEvent } from '../../api/protocol'
import type { HistoryItemPayload } from '../../api/types'
import { makeS } from '../../utils/css'
import { downloadCsv, downloadJson, exportFilename } from './exportData'
import { SessionListView } from './SessionListView'
import styles from './observability.module.css'

const s = makeS(styles)

/** 每页事件数（与后端 /events 的默认上限一致）。 */
const PAGE_LIMIT = 200
/** 实时跟随时内存里最多保留的事件数，防止长时间挂机无限增长。 */
const LIVE_BUFFER_LIMIT = 2000
/** 首次加载用「极大 seq」取最新一页（后端按 before 倒序分页）。 */
const LATEST_CURSOR = 1 << 30

type SessionEvent = RunEvent

/** 事件类型 → 台账色条样式（纯展示映射，不做业务判定）。 */
const TONE: Readonly<Record<string, string>> = {
  thought: 'phase',
  action: 'assistant',
  snapshot: 'checkpoint',
  stop: 'stop',
  error: 'error',
  'approval.requested': 'approval',
  'approval.resolved': 'approval',
  'clarification.requested': 'ask',
  'clarification.resolved': 'ask',
  'agent.checkpoint': 'checkpoint',
  'delegation.requested': 'delegation',
  'delegation.completed': 'delegation',
}

function toneOf(event: SessionEvent): string {
  return TONE[event.type] ?? ''
}

function isFailed(event: SessionEvent): boolean {
  const status = event.data.status
  return event.type === 'error' || status === 'failed' || status === 'aborted'
}

/** 一条事件的可读摘要：只读 data 里的展示字段，缺省回退 JSON 片段。 */
function summaryOf(event: SessionEvent): string {
  const data = event.data
  const pick = (...keys: string[]): string =>
    keys
      .map((key) => data[key])
      .filter((value) => typeof value === 'string' || typeof value === 'number')
      .join(' · ')
  switch (event.type) {
    case 'thought':
      return String(data.text ?? '')
    case 'action':
      return pick('title', 'detail') || pick('detail')
    case 'snapshot':
      return pick('status', 'state')
    case 'stop':
      return pick('status', 'state', 'stop_reason')
    case 'error':
      return pick('message')
    case 'approval.requested':
    case 'approval.resolved':
      return pick('title', 'kind', 'decision')
    case 'clarification.requested':
    case 'clarification.resolved':
      return pick('title', 'kind', 'answer')
    case 'agent.checkpoint':
      return pick('summary', 'stage', 'label')
    default:
      return JSON.stringify(data).slice(0, 200)
  }
}

function runLabel(runId: string): string {
  return runId === '' ? '—' : runId.slice(0, 8)
}

/**
 * Session Log（2026-11-13 恢复）：基于运行时 `run_events` 的原始事件台账。
 *
 * 与 Trace 模块的区别：Trace 记录的是新的全链路调用链（trace_events），
 * Session Log 是「用户/助手/工具/思考/阶段」的运行时事实流，二者数据源独立。
 * 因此本视图不受三模块开关约束，始终可用。
 */
export function SessionLogPanel() {
  const { t } = useTranslation()
  const [sessions, setSessions] = useState<HistoryItemPayload[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [events, setEvents] = useState<SessionEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState('')
  const [live, setLive] = useState(false)
  const [selected, setSelected] = useState<SessionEvent | null>(null)
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set())
  const [error, setError] = useState('')
  const eventsRef = useRef<SessionEvent[]>([])

  useEffect(() => {
    eventsRef.current = events
  }, [events])

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

  const loadLatest = useCallback(async (id: string): Promise<void> => {
    setLoading(true)
    setError('')
    try {
      const page = await getSessionEvents(id, LATEST_CURSOR, PAGE_LIMIT)
      setEvents(page)
      setHasMore(page.length >= PAGE_LIMIT)
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (sessionId === null) return
    setSelected(null)
    setCollapsed(new Set())
    setLive(false)
    void loadLatest(sessionId)
  }, [sessionId, loadLatest])

  // 实时跟随：从当前最大 seq 续订，按 seq 去重后追加（连接失败不弹错，保持历史可读）
  useEffect(() => {
    if (!live || sessionId === null) return undefined
    const last = eventsRef.current.at(-1)?.seq ?? 0
    return openSessionStream(sessionId, last, {
      onEvent: (event) => {
        if (event.seq === 0) return
        setEvents((prev) => {
          if (prev.some((item) => item.seq === event.seq)) return prev
          return [...prev, event].slice(-LIVE_BUFFER_LIMIT)
        })
      },
    })
  }, [live, sessionId])

  const loadOlder = async (): Promise<void> => {
    if (sessionId === null) return
    const before = events[0]?.seq ?? 0
    if (before <= 0) return
    setLoading(true)
    try {
      const page = await getSessionEvents(sessionId, before, PAGE_LIMIT)
      setEvents((prev) => [...page, ...prev])
      setHasMore(page.length >= PAGE_LIMIT)
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }

  const kinds = useMemo(
    () => [...new Set(events.map((item) => item.type))].filter((item) => item !== ''),
    [events],
  )

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    return events.filter((item) => {
      if (kind !== '' && item.type !== kind) return false
      if (keyword === '') return true
      return JSON.stringify(item).toLowerCase().includes(keyword)
    })
  }, [events, kind, query])

  // 以 run_id 分段：一次提交 = 一个 run，天然对应一轮
  const groups = useMemo(() => {
    const map = new Map<string, SessionEvent[]>()
    for (const item of filtered) {
      const key = item.run_id
      const bucket = map.get(key)
      if (bucket === undefined) map.set(key, [item])
      else bucket.push(item)
    }
    return [...map.entries()]
  }, [filtered])

  const toggleGroup = (key: string): void => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const exportCurrent = (format: 'json' | 'csv'): void => {
    const filename = exportFilename('session-log', sessionId ?? 'session', format)
    if (format === 'json') {
      downloadJson(filename, {
        session_id: sessionId,
        filters: { type: kind, query },
        events: filtered,
      })
      return
    }
    downloadCsv(
      filename,
      ['seq', 'type', 'run_id', 'ts', 'summary'],
      filtered.map((item) => [item.seq, item.type, item.run_id, item.ts, summaryOf(item)]),
    )
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
        <section className={s('obs-log')}>
          <div className={s('obs-toolbar')}>
            <div className={s('obs-toolbar__row')}>
              <input
                type="search"
                className={s('obs-input obs-input--grow')}
                placeholder={t('observability.toolbar.search_placeholder')}
                value={query}
                onChange={(event) => setQuery(event.currentTarget.value)}
              />
              <button
                type="button"
                className={s('obs-button')}
                disabled={loading || sessionId === null}
                onClick={() => sessionId !== null && void loadLatest(sessionId)}
              >
                {t('observability.toolbar.refresh')}
              </button>
              <button
                type="button"
                className={s(
                  live ? 'obs-button obs-button--active' : 'obs-button obs-button--ghost',
                )}
                aria-pressed={live}
                onClick={() => setLive((prev) => !prev)}
              >
                {t('observability.toolbar.live_follow')}
              </button>
              <button
                type="button"
                className={s('obs-button')}
                onClick={() => exportCurrent('json')}
              >
                {t('observability.toolbar.export_json')}
              </button>
              <button
                type="button"
                className={s('obs-button obs-button--ghost')}
                onClick={() => exportCurrent('csv')}
              >
                {t('observability.toolbar.export_csv')}
              </button>
            </div>
            <div className={s('obs-toolbar__chips')}>
              {kinds.map((item) => (
                <button
                  key={item}
                  type="button"
                  className={s(kind === item ? 'obs-chip obs-chip--active' : 'obs-chip')}
                  aria-pressed={kind === item}
                  onClick={() => setKind((prev) => (prev === item ? '' : item))}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>
          {error !== '' ? <p className={s('obs-status obs-status--error')}>{error}</p> : null}
          <p className={s('obs-note')}>
            events: {events.length} · {t('observability.module.session_log')}
          </p>
          {hasMore ? (
            <button
              type="button"
              className={s('obs-load-more')}
              disabled={loading}
              onClick={() => void loadOlder()}
            >
              {loading ? t('observability.loading') : t('observability.log.load_older')}
            </button>
          ) : null}
          <div className={s('obs-log__body')}>
            <div className={s('obs-ledger')}>
              {filtered.length === 0 ? (
                <p className={s('obs-empty')}>{t('observability.log.no_events')}</p>
              ) : (
                groups.map(([runId, items]) => (
                  <div key={runId}>
                    <button
                      type="button"
                      className={s('obs-turn-header')}
                      aria-expanded={!collapsed.has(runId)}
                      onClick={() => toggleGroup(runId)}
                    >
                      <span className={s('obs-turn-header__index')}>run {runLabel(runId)}</span>
                      <span className={s('obs-turn-header__state')}>{items.length}</span>
                      <span className={s('obs-turn-header__meta')}>
                        {items[0]?.ts ?? ''} → {items.at(-1)?.ts ?? ''}
                      </span>
                    </button>
                    {collapsed.has(runId)
                      ? null
                      : items.map((item) => {
                          const tone = toneOf(item)
                          return (
                            <button
                              key={item.seq}
                              type="button"
                              className={s(
                                'obs-row',
                                isFailed(item) && 'obs-row--failed',
                                selected?.seq === item.seq && 'obs-row--selected',
                              )}
                              onClick={() => setSelected(item)}
                            >
                              <span
                                className={s(
                                  'obs-row__kind',
                                  tone !== '' && `obs-row__kind--${tone}`,
                                )}
                              >
                                {item.type}
                              </span>
                              <span className={s('obs-row__label')}>#{item.seq}</span>
                              <span className={s('obs-row__text')}>{summaryOf(item)}</span>
                              <span className={s('obs-row__meta')}>{item.ts}</span>
                            </button>
                          )
                        })}
                  </div>
                ))
              )}
            </div>
            <aside className={s('obs-inspector')}>
              <h4 className={s('obs-inspector__title')}>{t('observability.inspector.title')}</h4>
              {selected === null ? (
                <p className={s('obs-empty')}>{t('observability.inspector.title')}</p>
              ) : (
                <pre className={s('obs-inspector__raw')}>{JSON.stringify(selected, null, 2)}</pre>
              )}
            </aside>
          </div>
        </section>
      </div>
    </div>
  )
}
