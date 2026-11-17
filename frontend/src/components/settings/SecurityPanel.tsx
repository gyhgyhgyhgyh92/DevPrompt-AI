import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { putSettings } from '../../api/endpoints'
import type { SettingsUpdate } from '../../api/types'
import { applyAppearanceTheme, useSettingsStore } from '../../stores/useSettingsStore'
import { Toggle } from '../ui/Toggle'
import { errorMessage } from './errorMessage'
import styles from './settings.module.css'
import { makeS } from '../../utils/css'

const s = makeS(styles)

/** 流程与安全面板（F-604 安全标签页）：软护栏调节 + 锁定项只读 + 遥测 + 清除本地数据。 */
export function SecurityPanel() {
  const { t } = useTranslation()
  const settings = useSettingsStore((state) => state.settings)
  const setSettings = useSettingsStore((state) => state.setSettings)
  const appearanceTheme = useSettingsStore((state) => state.appearance.theme)
  const clearLocalData = useSettingsStore((state) => state.clearLocalData)
  const [roundGuard, setRoundGuard] = useState('')
  const [costBudget, setCostBudget] = useState('')
  const [status, setStatus] = useState<{ ok: boolean; text: string }>({ ok: true, text: '' })
  const [isBusy, setIsBusy] = useState(false)
  const [isConfirmingClear, setIsConfirmingClear] = useState(false)

  // 本地数据被清除后外观回默认，这里把 data-theme 立即对齐（与 AppearancePanel 同一入口）
  useEffect(() => {
    applyAppearanceTheme(appearanceTheme)
  }, [appearanceTheme])

  useEffect(() => {
    if (!settings) return
    setRoundGuard(String(settings.process.followup_soft_round_guard))
    setCostBudget(String(settings.process.followup_cost_budget))
  }, [settings])

  if (!settings) {
    return <p className={s('settings-note')}>{t('settings.loading')}</p>
  }

  const saveProcess = async (process: NonNullable<SettingsUpdate['process']>) => {
    setIsBusy(true)
    try {
      const next = await putSettings({ process })
      setSettings(next)
      setStatus({ ok: true, text: t('settings.saved') })
    } catch (error) {
      setStatus({ ok: false, text: errorMessage(error, t('settings.save_failed')) })
    } finally {
      setIsBusy(false)
    }
  }

  const saveGuardParams = async () => {
    const rounds = Number(roundGuard.trim())
    const budget = Number(costBudget.trim())
    if (!Number.isFinite(rounds) || !Number.isFinite(budget)) {
      setStatus({ ok: false, text: t('settings.security.numeric_required') })
      return
    }
    await saveProcess({ followup_soft_round_guard: rounds, followup_cost_budget: budget })
  }

  /** 清除本地数据（双重确认）：只清 devprompt:v1: 前缀的本地留存，服务端数据不动。 */
  const handleClearLocalData = () => {
    if (!isConfirmingClear) {
      setIsConfirmingClear(true)
      return
    }
    clearLocalData()
    setIsConfirmingClear(false)
    setStatus({ ok: true, text: t('settings.security.cleared') })
  }

  return (
    <section className={s('settings-panel')} aria-label={t('settings.security.title')}>
      <h3 className={s('settings-panel__title')}>{t('settings.security.title')}</h3>
      <div className={s('settings-grid')}>
        <div className={s('settings-field')}>
          <label className={s('settings-label')} htmlFor="settings-round-guard">
            {t('settings.security.round_guard')}
          </label>
          <input
            id="settings-round-guard"
            className={s('settings-input')}
            value={roundGuard}
            onChange={(event) => setRoundGuard(event.currentTarget.value)}
          />
        </div>
        <div className={s('settings-field')}>
          <label className={s('settings-label')} htmlFor="settings-cost-budget">
            {t('settings.security.cost_budget')}
          </label>
          <input
            id="settings-cost-budget"
            className={s('settings-input')}
            value={costBudget}
            onChange={(event) => setCostBudget(event.currentTarget.value)}
          />
        </div>
        <div className={s('settings-field')}>
          <label className={s('settings-label')} htmlFor="settings-candidate-limit">
            {t('settings.security.candidate_limit')}
          </label>
          <input
            id="settings-candidate-limit"
            className={s('settings-input')}
            value={String(settings.locked.candidate_limit)}
            disabled
            readOnly
          />
          <span className={s('settings-hint')}>{t('settings.security.candidate_limit_hint')}</span>
        </div>
      </div>
      <div className={s('settings-actions')}>
        <button
          type="button"
          className={s('settings-btn settings-btn--primary')}
          disabled={isBusy}
          onClick={saveGuardParams}
        >
          {t('settings.security.save_params')}
        </button>
      </div>
      <div className={s('settings-row')}>
        <span className={s('settings-label')}>{t('settings.security.telemetry')}</span>
        <Toggle
          label={t('settings.security.telemetry')}
          checked={settings.process.telemetry}
          disabled={isBusy}
          onChange={(checked) => void saveProcess({ telemetry: checked })}
        />
      </div>
      <div className={s('settings-actions')}>
        <button
          type="button"
          className={s('settings-btn settings-btn--danger')}
          onClick={handleClearLocalData}
        >
          {isConfirmingClear ? t('settings.security.confirm_clear') : t('settings.security.clear')}
        </button>
        {isConfirmingClear ? (
          <button
            type="button"
            className={s('settings-btn')}
            onClick={() => setIsConfirmingClear(false)}
          >
            {t('common.cancel')}
          </button>
        ) : null}
      </div>
      <p className={s('settings-note')}>{t('settings.security.clear_note')}</p>
      {status.text !== '' ? (
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
    </section>
  )
}
