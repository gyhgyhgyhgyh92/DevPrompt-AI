import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getHistory } from '../../api/endpoints'
import type { HistoryItemPayload } from '../../api/types'
import { makeS } from '../../utils/css'
import { downloadCsv, downloadJson, exportFilename } from './exportData'
import { isFailedEvent, runLabel, summaryOf } from './eventPresentation'
import { SessionListView } from './SessionListView'
import { useSessionEventStream, type SessionEvent } from './useSessionEventStream'
import styles from './observability.module.css'

const s = makeS(styles)

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
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState('')
  const [selected, setSelected] = useState<SessionEvent | null>(null)
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set())
  /** 会话列表加载失败（与事件流错误分开，避免两类错误互相覆盖）。 */
  const [listError, setListError] = useState('')

  // 事件流（去重 / 缓冲 / 翻页 / SSE 订阅）收敛在共享 hook，桌面底部面板复用同一份
  const { events, loading, hasMore, error, isLive, setIsLive, reload, loadOlder } =
    useSessionEventStream(sessionId)

  useEffect(() => {
    let alive = true
    getHistory({ limit: 50 })
      .then((page) => {
        if (!alive) return
        setSessions(page.items)
        setSessionId((prev) => prev ?? page.items[0]?.session_id ?? null)
      })
      .catch((err: unknown) => alive && setListError(String(err)))
    return () => {
      alive = false
    }
  }, [])

  // 切换会话时重置选中项与分组折叠（事件流由 hook 自行处理会话切换）
  useEffect(() => {
    setSelected(null)
    setCollapsed(new Set())
  }, [sessionId])

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
                onClick={reload}
              >
                {t('observability.toolbar.refresh')}
              </button>
              <button
                type="button"
                className={s(
                  isLive ? 'obs-button obs-button--active' : 'obs-button obs-button--ghost',
                )}
                aria-pressed={isLive}
                onClick={() => setIsLive(!isLive)}
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
          {listError !== '' || error !== '' ? (
            <p className={s('obs-status obs-status--error')}>{listError || error}</p>
          ) : null}
          <p className={s('obs-note')}>
            events: {events.length} · {t('observability.module.session_log')}
          </p>
          {hasMore ? (
            <button
              type="button"
              className={s('obs-load-more')}
              disabled={loading}
              onClick={loadOlder}
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
                                isFailedEvent(item) && 'obs-row--failed',
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
