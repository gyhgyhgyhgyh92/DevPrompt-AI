import { useEffect, useState } from 'react'
import { putSettings } from '../../api/endpoints'
import type { SettingsUpdate } from '../../api/types'
import { applyAppearanceTheme, useSettingsStore } from '../../stores/useSettingsStore'
import { Toggle } from '../ui/Toggle'
import { errorMessage } from './errorMessage'
import './settings.css'

/** 流程与安全面板（F-604 安全标签页）：软护栏调节 + 锁定项只读 + 遥测 + 清除本地数据。 */
export function SecurityPanel() {
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
    return <p className="settings-note">设置加载中…</p>
  }

  const saveProcess = async (process: NonNullable<SettingsUpdate['process']>) => {
    setIsBusy(true)
    try {
      const next = await putSettings({ process })
      setSettings(next)
      setStatus({ ok: true, text: '已保存' })
    } catch (error) {
      setStatus({ ok: false, text: errorMessage(error, '保存失败') })
    } finally {
      setIsBusy(false)
    }
  }

  const saveGuardParams = async () => {
    const rounds = Number(roundGuard.trim())
    const budget = Number(costBudget.trim())
    if (!Number.isFinite(rounds) || !Number.isFinite(budget)) {
      setStatus({ ok: false, text: '护栏参数必须是数字' })
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
    setStatus({ ok: true, text: '已清除本地数据' })
  }

  return (
    <section className="settings-panel" aria-label="流程与安全">
      <h3 className="settings-panel__title">流程与安全</h3>
      <div className="settings-grid">
        <div className="settings-field">
          <label className="settings-label" htmlFor="settings-round-guard">
            反问软护栏轮数
          </label>
          <input
            id="settings-round-guard"
            className="settings-input"
            value={roundGuard}
            onChange={(event) => setRoundGuard(event.currentTarget.value)}
          />
        </div>
        <div className="settings-field">
          <label className="settings-label" htmlFor="settings-cost-budget">
            反问成本预算
          </label>
          <input
            id="settings-cost-budget"
            className="settings-input"
            value={costBudget}
            onChange={(event) => setCostBudget(event.currentTarget.value)}
          />
        </div>
        <div className="settings-field">
          <label className="settings-label" htmlFor="settings-candidate-limit">
            候选集上限（宪法 MUST-09 锁定）
          </label>
          <input
            id="settings-candidate-limit"
            className="settings-input"
            value={String(settings.locked.candidate_limit)}
            disabled
            readOnly
          />
          <span className="settings-hint">
            值来自后端 locked.candidate_limit，只读下发不接受修改
          </span>
        </div>
      </div>
      <div className="settings-actions">
        <button
          type="button"
          className="settings-btn settings-btn--primary"
          disabled={isBusy}
          onClick={saveGuardParams}
        >
          保存流程参数
        </button>
      </div>
      <div className="settings-row">
        <span className="settings-label">遥测</span>
        <Toggle
          label="遥测"
          checked={settings.process.telemetry}
          disabled={isBusy}
          onChange={(checked) => void saveProcess({ telemetry: checked })}
        />
      </div>
      <div className="settings-actions">
        <button
          type="button"
          className="settings-btn settings-btn--danger"
          onClick={handleClearLocalData}
        >
          {isConfirmingClear ? '确认清除？' : '清除本地数据'}
        </button>
        {isConfirmingClear ? (
          <button
            type="button"
            className="settings-btn"
            onClick={() => setIsConfirmingClear(false)}
          >
            取消
          </button>
        ) : null}
      </div>
      <p className="settings-note">
        仅清除本机 devprompt:v1: 本地留存（会话与记忆缓存），服务端记录不受影响
      </p>
      {status.text !== '' ? (
        <p
          className={
            status.ok
              ? 'settings-status settings-status--ok'
              : 'settings-status settings-status--error'
          }
        >
          {status.text}
        </p>
      ) : null}
    </section>
  )
}
