import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  getHistory,
  getObsAlerts,
  getObsMetricsConfig,
  getObsMetricsSummary,
} from '../../api/endpoints'
import type { HistoryItemPayload } from '../../api/types'
import { SessionListView } from './SessionListView'
import { makeS } from '../../utils/css'
import styles from './observability.module.css'

const s = makeS(styles)

type Item = Record<string, unknown>

/** Metrics 模块：多维聚合、趋势条、阈值配置与告警历史。 */
export function MetricsPanel() {
  const { t } = useTranslation()
  const [sessions, setSessions] = useState<HistoryItemPayload[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [groupBy, setGroupBy] = useState('kind')
  const [bucket, setBucket] = useState('none')
  const [series, setSeries] = useState<Item[]>([])
  const [alerts, setAlerts] = useState<Item[]>([])
  const [config, setConfig] = useState<Record<string, unknown>>({})
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
    let alive = true
    Promise.all([getObsMetricsConfig(), getObsAlerts({ status: '', limit: 50, offset: 0 })])
      .then(([cfg, alertPage]) => {
        if (!alive) return
        setConfig(cfg.config)
        setAlerts(alertPage.items)
      })
      .catch((err: unknown) => alive && setError(String(err)))
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    if (sessionId === null) return
    let alive = true
    getObsMetricsSummary({ session_id: sessionId, group_by: groupBy, bucket })
      .then((data) => alive && setSeries(data.items))
      .catch((err: unknown) => alive && setError(String(err)))
    return () => {
      alive = false
    }
  }, [sessionId, groupBy, bucket])

  const maxP95 = useMemo(() => {
    let max = 1
    for (const item of series) {
      for (const point of (item.points as Item[]) ?? []) {
        max = Math.max(max, Number(point.p95_ms ?? 0))
      }
    }
    return max
  }, [series])

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
        <div className={s('obs-toolbar')}>
          <div className={s('obs-toolbar__row')}>
            <label className={s('obs-field')}>
              <span className={s('obs-field__label')}>group</span>
              <select
                className={s('obs-select obs-select--compact')}
                value={groupBy}
                onChange={(event) => setGroupBy(event.currentTarget.value)}
              >
                {['kind', 'name', 'model', 'turn', 'status'].map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            <label className={s('obs-field')}>
              <span className={s('obs-field__label')}>bucket</span>
              <select
                className={s('obs-select obs-select--compact')}
                value={bucket}
                onChange={(event) => setBucket(event.currentTarget.value)}
              >
                {['none', 'minute', 'hour', 'day'].map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            <span className={s('obs-note')}>
              P95 warn: {String(config.p95_ms_warn ?? '—')} ms · error{' '}
              {String(config.error_rate_warn ?? '—')} · tokens {String(config.token_warn ?? '—')}
            </span>
          </div>
        </div>
        {error !== '' ? <p className={s('obs-status obs-status--error')}>{error}</p> : null}
        <div className={s('obs-metrics')}>
          {series.length === 0 ? (
            <p className={s('obs-empty')}>{t('observability.metrics.no_data')}</p>
          ) : (
            series.map((item) => (
              <div key={`${item.dimension}-${item.key}`} className={s('obs-card')}>
                <h4 className={s('obs-card__title')}>{String(item.key)}</h4>
                <ul className={s('obs-bars')}>
                  {((item.points as Item[]) ?? []).map((point, index) => (
                    <li key={`${String(item.key)}-${index}`} className={s('obs-bar')}>
                      <span className={s('obs-bar__label')}>{String(point.bucket || 'all')}</span>
                      <span className={s('obs-bar__track')}>
                        <span
                          className={s('obs-bar__fill')}
                          style={{ width: `${(Number(point.p95_ms ?? 0) / maxP95) * 100}%` }}
                        />
                      </span>
                      <span className={s('obs-bar__value')}>
                        {Number(point.count ?? 0)} / {Number(point.failed ?? 0)} fails /{' '}
                        {Number(point.p95_ms ?? 0)}ms
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))
          )}
          <div className={s('obs-card')}>
            <h4 className={s('obs-card__title')}>{t('observability.metrics.alerts')}</h4>
            {alerts.length === 0 ? (
              <p className={s('obs-empty')}>{t('observability.metrics.no_data')}</p>
            ) : (
              <ul className={s('obs-bars')}>
                {alerts.map((alert) => (
                  <li key={String(alert.alert_id)} className={s('obs-bar')}>
                    <span className={s('obs-bar__label')}>
                      {String(alert.severity)} · {String(alert.rule_id)}
                    </span>
                    <span className={s('obs-bar__track')}>
                      <span className={s('obs-bar__fill')} style={{ width: '100%' }} />
                    </span>
                    <span className={s('obs-bar__value')}>{String(alert.message)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
