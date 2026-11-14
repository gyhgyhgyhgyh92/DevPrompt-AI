import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getHistory, getObsEvent, getObsEvents, getObsTraces } from '../../api/endpoints'
import type { HistoryItemPayload } from '../../api/types'
import { SessionListView } from './SessionListView'
import { downloadCsv, downloadJson, exportFilename } from './exportData'
import { makeS } from '../../utils/css'
import styles from './observability.module.css'

const s = makeS(styles)

type Item = Record<string, unknown>

function text(value: unknown): string {
  return typeof value === 'string' ? value : value === undefined ? '' : JSON.stringify(value)
}

/** Trace 模块：调用链列表 + 事件台账 + 全量事件检查器 + 导出。 */
export function TracePanel() {
  const { t } = useTranslation()
  const [sessions, setSessions] = useState<HistoryItemPayload[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [traces, setTraces] = useState<Item[]>([])
  const [events, setEvents] = useState<Item[]>([])
  const [cursor, setCursor] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [kind, setKind] = useState('')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<Item | null>(null)
  const [error, setError] = useState('')

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
    setError('')
    setEvents([])
    setCursor(0)
    Promise.all([getObsTraces(sessionId), getObsEvents(sessionId, { limit: 200 })])
      .then(([tracePage, eventPage]) => {
        if (!alive) return
        setTraces(tracePage.items)
        setEvents(eventPage.items)
        setHasMore(eventPage.has_more)
        setCursor(eventPage.next_cursor)
      })
      .catch((err: unknown) => alive && setError(String(err)))
    return () => {
      alive = false
    }
  }, [sessionId])

  const kinds = useMemo(
    () => [...new Set(events.map((item) => String(item.kind ?? '')))].filter(Boolean),
    [events],
  )
  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    return events.filter((item) => {
      if (kind !== '' && item.kind !== kind) return false
      if (keyword === '') return true
      return JSON.stringify(item).toLowerCase().includes(keyword)
    })
  }, [events, kind, query])

  const loadOlder = async (): Promise<void> => {
    if (sessionId === null || cursor <= 0) return
    const page = await getObsEvents(sessionId, { kind, cursor, limit: 200 })
    setEvents((prev) => [...page.items, ...prev])
    setHasMore(page.has_more)
    setCursor(page.next_cursor)
  }

  const openEvent = async (eventId: string): Promise<void> => {
    const data = await getObsEvent(eventId)
    setSelected(data.event)
  }

  const exportCurrent = (format: 'json' | 'csv'): void => {
    const filename = exportFilename('trace', sessionId ?? 'session', format)
    if (format === 'json') {
      downloadJson(filename, { session_id: sessionId, filters: { kind, query }, events: filtered })
      return
    }
    downloadCsv(
      filename,
      ['seq', 'kind', 'name', 'status', 'started_at', 'duration_ms', 'event_id'],
      filtered.map((item) => [
        Number(item.seq ?? 0),
        String(item.kind ?? ''),
        String(item.name ?? ''),
        String(item.status ?? ''),
        String(item.started_at ?? ''),
        Number(item.duration_ms ?? 0),
        String(item.event_id ?? ''),
      ]),
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
            traces: {traces.length} · events: {events.length}
          </p>
          {hasMore ? (
            <button type="button" className={s('obs-load-more')} onClick={() => void loadOlder()}>
              {t('observability.log.load_older')}
            </button>
          ) : null}
          <div className={s('obs-log__body')}>
            <div className={s('obs-ledger')}>
              {filtered.length === 0 ? (
                <p className={s('obs-empty')}>{t('observability.log.no_events')}</p>
              ) : (
                filtered.map((item) => (
                  <button
                    key={String(item.event_id)}
                    type="button"
                    className={s(
                      'obs-row',
                      item.status === 'failed' && 'obs-row--failed',
                      selected?.event_id === item.event_id && 'obs-row--selected',
                    )}
                    onClick={() => void openEvent(String(item.event_id))}
                  >
                    <span className={s('obs-row__kind')}>{String(item.kind ?? '')}</span>
                    <span className={s('obs-row__label')}>{String(item.name ?? '')}</span>
                    <span className={s('obs-row__text')}>{text(item.output_preview)}</span>
                    <span className={s('obs-row__meta')}>{String(item.duration_ms ?? 0)} ms</span>
                  </button>
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
