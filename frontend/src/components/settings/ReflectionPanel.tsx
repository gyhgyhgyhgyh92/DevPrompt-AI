import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getHealth, putSettings } from '../../api/endpoints'
import type { SettingsUpdate } from '../../api/types'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { Toggle } from '../ui/Toggle'
import { errorMessage } from './errorMessage'
import styles from './settings.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

/** 侧车链路状态：未启用 / 已连接 / 不可达（由 /health 的 reflection 检查项驱动）。 */
type LinkState = 'off' | 'ok' | 'down'

interface LinkInfo {
  state: LinkState
  detail: string
}

/**
 * 设置中心 · 自进化（2026-11-22）。
 *
 * 三项配置：总开关、侧车地址、召回条数。开关与保存均即时生效（后端按最新配置重建
 * 经验库适配器）；侧车连通性来自 `GET /health` 的 `reflection` 检查项，未启用时后端
 * 返回稳定标记 `disabled`，文案一律在本组件按 i18n 渲染（零业务判定，MUST-08）。
 */
export function ReflectionPanel() {
  const { t } = useTranslation()
  const settings = useSettingsStore((state) => state.settings)
  const setSettings = useSettingsStore((state) => state.setSettings)
  const [baseUrl, setBaseUrl] = useState('')
  const [topK, setTopK] = useState('5')
  const [isBusy, setIsBusy] = useState(false)
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null)
  const [link, setLink] = useState<LinkInfo>({ state: 'off', detail: '' })

  const reflection = settings?.reflection

  // 后端设置到达后同步草稿（其余设置段由各自面板负责，这里只读 reflection）
  useEffect(() => {
    if (reflection === undefined) return
    setBaseUrl(reflection.base_url)
    setTopK(String(reflection.top_k))
  }, [reflection])

  /** 读 /health 的 reflection 项；不走 store（诊断类数据一次性使用）。 */
  const refreshLink = useCallback(async () => {
    try {
      const health = await getHealth()
      const check = health.checks.find((item) => item.name === 'reflection')
      if (check === undefined) {
        setLink({ state: 'down', detail: '' })
        return
      }
      if (check.detail === 'disabled') {
        setLink({ state: 'off', detail: '' })
        return
      }
      setLink({ state: check.ok ? 'ok' : 'down', detail: check.detail ?? '' })
    } catch {
      setLink({ state: 'down', detail: '' })
    }
  }, [])

  useEffect(() => {
    void refreshLink()
  }, [refreshLink])

  const saveReflection = async (patch: NonNullable<SettingsUpdate['reflection']>) => {
    setIsBusy(true)
    setStatus(null)
    try {
      const next = await putSettings({ reflection: patch })
      setSettings(next)
      setStatus({ ok: true, text: t('settings.saved') })
      await refreshLink()
    } catch (error) {
      setStatus({ ok: false, text: errorMessage(error, t('settings.save_failed')) })
    } finally {
      setIsBusy(false)
    }
  }

  const saveAdvanced = async (): Promise<void> => {
    const parsed = Number(topK.trim())
    // 与服务端 Field(ge=1, le=20) 对齐：越界在本地拦下，避免只看到通用的保存失败
    if (!Number.isFinite(parsed) || parsed < 1 || parsed > 20) {
      setStatus({ ok: false, text: t('settings.reflection.top_k_invalid') })
      return
    }
    await saveReflection({ base_url: baseUrl.trim(), top_k: Math.round(parsed) })
  }

  const linkText =
    link.state === 'off'
      ? t('settings.reflection.link_off')
      : link.state === 'ok'
        ? t('settings.reflection.link_ok')
        : t('settings.reflection.link_down')

  return (
    <section className={s('settings-panel')} aria-label={t('settings.reflection.title')}>
      <h3 className={s('settings-panel__title')}>{t('settings.reflection.title')}</h3>
      <p className={s('settings-panel__desc')}>{t('settings.reflection.desc')}</p>
      <div className={s('settings-row')}>
        <span className={s('settings-label')}>{t('settings.reflection.enabled')}</span>
        <div className={s('settings-row')}>
          <Toggle
            label={t('settings.reflection.enabled')}
            checked={reflection?.enabled === true}
            disabled={isBusy}
            onChange={(checked) => void saveReflection({ enabled: checked })}
          />
          <span
            className={s(
              link.state === 'ok'
                ? 'settings-status settings-status--ok'
                : link.state === 'down'
                  ? 'settings-status settings-status--error'
                  : 'settings-status',
            )}
            role="status"
          >
            {linkText}
            {link.state === 'down' && link.detail !== '' ? `（${link.detail}）` : ''}
          </span>
        </div>
      </div>
      <div className={s('settings-grid')}>
        <div className={s('settings-field')}>
          <label className={s('settings-label')} htmlFor="settings-reflection-base-url">
            {t('settings.reflection.base_url')}
          </label>
          <input
            id="settings-reflection-base-url"
            className={s('settings-input')}
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.currentTarget.value)}
            placeholder="http://127.0.0.1:3111"
          />
        </div>
        <div className={s('settings-field')}>
          <label className={s('settings-label')} htmlFor="settings-reflection-top-k">
            {t('settings.reflection.top_k')}
          </label>
          <input
            id="settings-reflection-top-k"
            className={s('settings-input')}
            value={topK}
            onChange={(event) => setTopK(event.currentTarget.value)}
          />
          <span className={s('settings-hint')}>{t('settings.reflection.top_k_hint')}</span>
        </div>
      </div>
      <div className={s('settings-actions')}>
        <button
          type="button"
          className={s('settings-btn settings-btn--primary')}
          disabled={isBusy}
          onClick={() => void saveAdvanced()}
        >
          {t('settings.reflection.save')}
        </button>
      </div>
      {status !== null ? (
        <p
          className={s(
            status.ok
              ? 'settings-status settings-status--ok'
              : 'settings-status settings-status--error',
          )}
        >
          {status.text}
        </p>
      ) : null}
      <p className={s('settings-note')}>{t('settings.reflection.note')}</p>
    </section>
  )
}
