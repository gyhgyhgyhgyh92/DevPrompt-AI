import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { getSettings } from '../api/endpoints'
import { ObservabilityPanel } from '../features/obs/ObservabilityPanel'
import { useSettingsStore } from '../stores/useSettingsStore'
import { makeS } from '../utils/css'
import styles from './ObservabilityPage.module.css'

const s = makeS(styles)

/**
 * 可观测性独立页面（/observability，2026-11-16）：内容自设置中心弹窗迁出，
 * 顶部为页面级标题 + 返回工作台，下方复用 obs 外壳（模块开关 + 四视图标签）。
 *
 * 直达 URL / 刷新时后端设置可能尚未到位（启动预加载失败或仍在途中）：
 * 缺 observability 段会让模块开关回退为「全开」，进而请求后端已禁用的模块。
 * 失败静默、不重试（MUST-15）；页面只做编排与兜底，零业务判定（MUST-08/10）。
 */
export function ObservabilityPage() {
  const { t } = useTranslation()
  const settings = useSettingsStore((s) => s.settings)
  const setSettings = useSettingsStore((s) => s.setSettings)

  useEffect(() => {
    if (settings?.observability !== undefined) return
    let cancelled = false
    getSettings()
      .then((next) => {
        if (!cancelled) setSettings(next)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [settings, setSettings])

  return (
    <section className={s('obs-page')}>
      <div className={s('obs-page__head')}>
        <h1>{t('observability.title')}</h1>
        <Link to="/">{t('observability.back_workbench')}</Link>
      </div>
      <ObservabilityPanel />
    </section>
  )
}
