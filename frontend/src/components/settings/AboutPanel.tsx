import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import {
  checkForUpdates,
  dismissUpdate,
  downloadUpdate,
  getUpdateState,
  installUpdate,
  isUpdateSupported,
  subscribeUpdateState,
  type UpdateState,
} from '../../api/desktopUpdate'
import { errorMessage } from './errorMessage'
import settingsStyles from './settings.module.css'
import aboutStyles from './AboutPanel.module.css'
import { makeS } from '../../utils/css'

const s = makeS(settingsStyles)
const a = makeS(aboutStyles)

const RELEASES_URL = 'https://github.com/gyhgyhgyhgyh92/DevPrompt-AI/releases'

function formatSize(bytes: number | undefined): string {
  if (bytes === undefined || !Number.isFinite(bytes) || bytes <= 0) return ''
  const mb = bytes / (1024 * 1024)
  return `${mb >= 100 ? Math.round(mb) : mb.toFixed(1)} MB`
}

/** 设置中心 · 关于与更新（2026-11-27）：版本、检查/下载/安装与进度。 */
export function AboutPanel(): ReactNode {
  const { t } = useTranslation()
  const supported = isUpdateSupported()
  const [state, setState] = useState<UpdateState | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')

  useEffect(() => {
    if (!supported) return
    let cancelled = false
    getUpdateState()
      .then((next) => {
        if (!cancelled && next !== null) setState(next)
      })
      .catch((error: unknown) => {
        if (!cancelled) setActionError(errorMessage(error, t('settings.about.action_failed')))
      })
    const unsubscribe = subscribeUpdateState((next) => setState(next))
    return () => {
      cancelled = true
      unsubscribe()
    }
  }, [supported, t])

  const run = (action: () => Promise<UpdateState | null>): void => {
    if (busy) return
    setBusy(true)
    setActionError('')
    void action()
      .then((next) => {
        if (next !== null) setState(next)
      })
      .catch((error: unknown) =>
        setActionError(errorMessage(error, t('settings.about.action_failed'))),
      )
      .finally(() => setBusy(false))
  }

  const phase = state?.phase ?? 'idle'
  const runtimeSupported = supported && (state?.supported ?? true)
  const locked = busy || phase === 'checking' || phase === 'downloading' || phase === 'installing'
  const percent = Math.max(0, Math.min(100, Math.round(state?.progressPercent ?? 0)))
  const size = formatSize(state?.sizeBytes)
  const errorText = actionError !== '' ? actionError : (state?.error ?? '')

  let statusText = t('settings.about.idle')
  if (phase === 'checking') statusText = t('settings.about.checking')
  else if (phase === 'up-to-date') statusText = t('settings.about.up_to_date')
  else if (phase === 'available') {
    statusText = `${t('settings.about.available', { version: state?.availableVersion ?? '' })}${
      size === '' ? '' : ` · ${t('settings.about.size', { size })}`
    }`
  } else if (phase === 'downloading') {
    statusText = t('settings.about.downloading', { percent })
  } else if (phase === 'downloaded') {
    statusText = t('settings.about.downloaded', { version: state?.availableVersion ?? '' })
  } else if (phase === 'installing') statusText = t('settings.about.installing')
  else if (phase === 'error') statusText = t('settings.about.failed')

  return (
    <section className={s('settings-panel')} aria-label={t('settings.about.title')}>
      <h3 className={s('settings-panel__title')}>{t('settings.about.title')}</h3>
      <p className={s('settings-panel__desc')}>{t('settings.about.desc')}</p>

      <div className={s('settings-field')}>
        <span className={s('settings-label')}>{t('settings.about.current_version')}</span>
        <span className={s('settings-hint')}>v{state?.currentVersion ?? '—'}</span>
      </div>

      {!supported ? (
        <p className={s('settings-hint')}>{t('settings.about.unsupported')}</p>
      ) : !runtimeSupported ? (
        <p className={s('settings-hint')}>{t('settings.about.windows_only')}</p>
      ) : (
        <>
          <p className={s('settings-status')} aria-live="polite">
            {statusText}
          </p>

          {phase === 'downloading' ? (
            <div
              className={a('about-progress')}
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={percent}
            >
              <div className={a('about-progress__bar')} style={{ width: `${percent}%` }} />
            </div>
          ) : null}

          <div className={s('settings-actions')}>
            {phase === 'available' ? (
              <>
                <button
                  type="button"
                  className={s('settings-btn settings-btn--primary')}
                  disabled={locked}
                  onClick={() => run(downloadUpdate)}
                >
                  {t('settings.about.download')}
                </button>
                <button
                  type="button"
                  className={s('settings-btn')}
                  disabled={locked}
                  onClick={() => run(dismissUpdate)}
                >
                  {t('settings.about.later')}
                </button>
              </>
            ) : null}

            {phase === 'downloaded' ? (
              <>
                <button
                  type="button"
                  className={s('settings-btn settings-btn--primary')}
                  disabled={locked}
                  onClick={() => run(installUpdate)}
                >
                  {t('settings.about.install')}
                </button>
                <button
                  type="button"
                  className={s('settings-btn')}
                  disabled={locked}
                  onClick={() => run(dismissUpdate)}
                >
                  {t('settings.about.later')}
                </button>
              </>
            ) : null}

            {phase !== 'available' && phase !== 'downloaded' ? (
              <button
                type="button"
                className={s('settings-btn settings-btn--primary')}
                disabled={locked}
                onClick={() => run(checkForUpdates)}
              >
                {phase === 'checking' ? t('settings.about.checking') : t('settings.about.check')}
              </button>
            ) : null}
          </div>
        </>
      )}

      {errorText !== '' ? (
        <p className={s('settings-status settings-status--error')}>{errorText}</p>
      ) : null}

      <p className={s('settings-note')}>
        <a href={RELEASES_URL} target="_blank" rel="noopener noreferrer">
          {t('settings.about.release_notes')}
        </a>
      </p>
    </section>
  )
}
