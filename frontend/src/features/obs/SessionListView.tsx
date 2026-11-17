import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { HistoryItemPayload } from '../../api/types'
import { makeS } from '../../utils/css'
import styles from './observability.module.css'

const s = makeS(styles)

export interface SessionListViewProps {
  sessions: HistoryItemPayload[]
  selectedId: string | null
  loading: boolean
  error: string
  hasMore: boolean
  onSelect: (sessionId: string) => void
  onLoadMore: () => void
}

/** 左栏会话列表：搜索/项目筛选均在已加载页上完成，翻页由「加载更多」触发。 */
export function SessionListView(props: SessionListViewProps) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [project, setProject] = useState('')

  const projects = useMemo(
    () => [...new Set(props.sessions.map((item) => item.project).filter(Boolean))],
    [props.sessions],
  )
  const visible = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    return props.sessions.filter((item) => {
      if (project !== '' && item.project !== project) return false
      if (keyword === '') return true
      return (
        item.title.toLowerCase().includes(keyword) || item.project.toLowerCase().includes(keyword)
      )
    })
  }, [props.sessions, project, query])

  return (
    <aside className={s('obs-sessions')} aria-label={t('observability.sessions.title')}>
      <h3 className={s('obs-sessions__title')}>{t('observability.sessions.title')}</h3>
      <input
        type="search"
        className={s('obs-input')}
        value={query}
        placeholder={t('observability.sessions.search_placeholder')}
        aria-label={t('observability.sessions.search_placeholder')}
        onChange={(event) => setQuery(event.currentTarget.value)}
      />
      <select
        className={s('obs-select')}
        value={project}
        aria-label={t('observability.sessions.all_projects')}
        onChange={(event) => setProject(event.currentTarget.value)}
      >
        <option value="">{t('observability.sessions.all_projects')}</option>
        {projects.map((item) => (
          <option key={item} value={item}>
            {item}
          </option>
        ))}
      </select>
      {props.error !== '' ? (
        <p className={s('obs-status obs-status--error')}>{props.error}</p>
      ) : null}
      <ul className={s('obs-sessions__list')}>
        {visible.map((item) => (
          <li key={item.session_id}>
            <button
              type="button"
              aria-current={item.session_id === props.selectedId ? 'true' : undefined}
              className={s(
                item.session_id === props.selectedId
                  ? 'obs-sessions__item obs-sessions__item--active'
                  : 'obs-sessions__item',
              )}
              onClick={() => props.onSelect(item.session_id)}
            >
              <span className={s('obs-sessions__name')}>{item.title || item.session_id}</span>
              <span className={s('obs-sessions__meta')}>
                {item.project} · {item.updated_at}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {visible.length === 0 && !props.loading ? (
        <p className={s('obs-empty')}>{t('observability.sessions.no_match')}</p>
      ) : null}
      {props.hasMore ? (
        <button
          type="button"
          className={s('obs-button obs-button--ghost')}
          disabled={props.loading}
          onClick={props.onLoadMore}
        >
          {props.loading ? t('observability.loading') : t('observability.sessions.load_more')}
        </button>
      ) : null}
    </aside>
  )
}
