/**
 * 桌面底部面板（2026-11-17）：可折叠「运行日志」——实时会话事件流。
 *
 * 对标 Trae SOLO / VS Code 的底部面板（Terminal / Output 区）：面板头常驻可点，
 * 展开后为单色等宽日志行。数据源是 `useSessionEventStream`——与 Session Log 视图
 * **共用同一份**实时事件流（去重 / 缓冲上限 / SSE 续订只有一份实现）。
 *
 * 订阅纪律：面板收起时内容组件整体卸载，SSE 由 effect cleanup 关闭，
 * 不留后台空转；不自动重连（MUST-15）。
 */
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronRight, Radio } from 'lucide-react'
import { useOptimizeStore } from '../../stores/useOptimizeStore'
import { isFailedEvent, summaryOf } from '../../features/obs/eventPresentation'
import { useSessionEventStream } from '../../features/obs/useSessionEventStream'
import { makeS } from '../../utils/css'
import styles from './DesktopBottomPanel.module.css'

const s = makeS(styles)

/** 日志区最多渲染的尾部行数（更早的历史用「加载更早」翻页）。 */
const VISIBLE_TAIL = 200

export function DesktopBottomPanel(): ReactNode {
  const { t } = useTranslation()
  const [isOpen, setOpen] = useState(false)
  const bodyId = useId()
  const sessionId = useOptimizeStore((state) => state.sessionId)

  return (
    <section className={s('app-panel')} aria-label={t('desktop.panel.label')}>
      <button
        type="button"
        className={s('app-panel__head')}
        aria-expanded={isOpen}
        aria-controls={bodyId}
        onClick={() => setOpen((prev) => !prev)}
      >
        {isOpen ? (
          <ChevronDown size={14} strokeWidth={1.5} aria-hidden="true" />
        ) : (
          <ChevronRight size={14} strokeWidth={1.5} aria-hidden="true" />
        )}
        <span className={s('app-panel__title')}>{t('desktop.panel.title')}</span>
      </button>
      {isOpen ? (
        <div className={s('app-panel__body')} id={bodyId}>
          <DesktopBottomPanelLog sessionId={sessionId} />
        </div>
      ) : null}
    </section>
  )
}

/** 日志内容：订阅实时事件流并渲染尾部行。 */
function DesktopBottomPanelLog({ sessionId }: { sessionId: string | null }): ReactNode {
  const { t } = useTranslation()
  const { events, error, hasMore, loading, loadOlder, setIsLive } = useSessionEventStream(sessionId)
  const bodyRef = useRef<HTMLDivElement | null>(null)
  const tail = events.slice(-VISIBLE_TAIL)

  // 面板展开即进入实时跟随（桌面端运行日志的默认形态）
  useEffect(() => {
    setIsLive(true)
  }, [setIsLive])

  // 实时跟随：新事件到达时滚到底部（终端式阅读位）
  useEffect(() => {
    const node = bodyRef.current
    if (node === null) return
    node.scrollTop = node.scrollHeight
  }, [events.length])

  return (
    <div className={s('app-panel__log')} ref={bodyRef}>
      {error !== '' ? <p className={s('app-panel__error')}>{error}</p> : null}
      {sessionId === null ? (
        <p className={s('app-panel__empty')}>{t('desktop.panel.no_session')}</p>
      ) : tail.length === 0 && !loading ? (
        <p className={s('app-panel__empty')}>{t('desktop.panel.no_events')}</p>
      ) : (
        <ul className={s('app-panel__list')}>
          {tail.map((event) => (
            <li
              key={event.seq}
              className={s('app-panel__row', isFailedEvent(event) && 'app-panel__row--failed')}
            >
              <span className={s('app-panel__seq')}>#{event.seq}</span>
              <span className={s('app-panel__type')}>{event.type}</span>
              <span className={s('app-panel__summary')}>{summaryOf(event)}</span>
            </li>
          ))}
        </ul>
      )}
      {hasMore ? (
        <button
          type="button"
          className={s('app-panel__more')}
          disabled={loading}
          onClick={loadOlder}
        >
          {loading ? t('observability.loading') : t('observability.log.load_older')}
        </button>
      ) : null}
      <p className={s('app-panel__hint')}>
        <Radio size={12} strokeWidth={1.5} aria-hidden="true" />
        {t('desktop.panel.hint')}
      </p>
    </div>
  )
}
