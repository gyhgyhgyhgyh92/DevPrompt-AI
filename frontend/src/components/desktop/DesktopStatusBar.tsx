/**
 * 桌面状态栏（2026-11-17，22px）：项目路径 · 会话号 · 状态机态 · SSE · API · 当前模型。
 *
 * 对标 VS Code `.statusbar`（22px / 12px）与 Trae SOLO 的状态 chip
 * （`.siteStatus-*`：18px 高、4px 圆角、浅底）。
 *
 * 信息全部**镜像**既有来源：状态机态与 SSE 态来自 `useOptimizeStore`，
 * 项目名来自 `useHistoryStore`，当前模型来自 `useSettingsStore` 的 `is_active` 标记，
 * API 态由外壳传入（避免重复请求 /health）。前端不做任何业务判定（MUST-08）。
 */
import { useTranslation } from 'react-i18next'
import type { ReactNode } from 'react'
import { useOptimizeStore } from '../../stores/useOptimizeStore'
import { useHistoryStore } from '../../stores/useHistoryStore'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { makeS } from '../../utils/css'
import styles from './DesktopStatusBar.module.css'

const s = makeS(styles)

export type DesktopApiStatus = 'checking' | 'ok' | 'down'

export interface DesktopStatusBarProps {
  /** API 可用性（外壳已拉过 /health，此处只消费，不重复请求）。 */
  apiStatus: DesktopApiStatus
}

/** SSE 连接态 → 视觉色调。取既有状态色，不引入新的语义判定。 */
const SSE_TONE: Record<string, string> = {
  idle: 'app-statusbar__chip--idle',
  connecting: 'app-statusbar__chip--running',
  open: 'app-statusbar__chip--ok',
  error: 'app-statusbar__chip--down',
}

export function DesktopStatusBar({ apiStatus }: DesktopStatusBarProps): ReactNode {
  const { t } = useTranslation()
  // 逐字段订阅（MUST-16：精确 selector，不整表订阅）
  const sessionId = useOptimizeStore((state) => state.sessionId)
  const flowState = useOptimizeStore((state) => state.state)
  const flowStatus = useOptimizeStore((state) => state.status)
  const sseStatus = useOptimizeStore((state) => state.sseStatus)
  const history = useHistoryStore((state) => state.history)
  const settings = useSettingsStore((state) => state.settings)

  const activeProject =
    sessionId === null ? undefined : history.find((item) => item.session_id === sessionId)?.project
  const activeModel = settings?.models.find((model) => model.is_active)?.model_id

  const sseTone = SSE_TONE[sseStatus] ?? ''

  return (
    <footer className={s('app-statusbar')} aria-label={t('desktop.status.label')}>
      <span className={s('app-statusbar__path')} title={activeProject ?? undefined}>
        {activeProject ?? t('app.no_project')}
      </span>

      <span className={s('app-statusbar__spacer')} />

      {sessionId !== null ? (
        <>
          <span className={s('app-statusbar__item')} title={sessionId}>
            {t('desktop.status.session')} #{sessionId.slice(-6)}
          </span>
          <span className={s('app-statusbar__chip')}>{flowState}</span>
          {flowStatus !== null ? (
            <span className={s('app-statusbar__chip')}>{flowStatus}</span>
          ) : null}
        </>
      ) : (
        <span className={s('app-statusbar__item')}>{t('desktop.status.no_session')}</span>
      )}

      <span className={s('app-statusbar__chip', sseTone)}>
        {t(`desktop.status.sse.${sseStatus}`)}
      </span>

      <span className={s('app-statusbar__chip', `app-statusbar__chip--${apiStatus}`)}>
        {t(`app.status_${apiStatus}`)}
      </span>

      {activeModel !== undefined ? (
        <span className={s('app-statusbar__item')}>{activeModel}</span>
      ) : null}
    </footer>
  )
}
