import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Info } from 'lucide-react'
import { putSettings } from '../../api/endpoints'
import { useSettingsStore } from '../../stores/useSettingsStore'
import { makeS } from '../../utils/css'
import { Tooltip } from '../../components/ui/Tooltip'
import { errorMessage } from '../../components/settings/errorMessage'
import { MetricsPanel } from './MetricsPanel'
import { ReplayPanel } from './ReplayPanel'
import { SessionLogPanel } from './SessionLogPanel'
import { TracePanel } from './TracePanel'
import styles from './observability.module.css'

const s = makeS(styles)

type ModuleKey = 'trace' | 'metrics' | 'replay'
type ViewKey = 'session-log' | ModuleKey

const MODULES: ModuleKey[] = ['trace', 'metrics', 'replay']
const MODULE_LABEL: Record<ModuleKey, string> = {
  trace: 'Trace',
  metrics: 'Metrics',
  replay: 'Replay',
}

/** 模块气泡文案（定义 / 核心功能 / 使用场景），来自 i18n。 */
interface ModuleTip {
  title: string
  definition: string
  features: string
  scenarios: string
}

/**
 * 可观测性模块标签：悬停/聚焦时在标签下方显示中文气泡解释。
 *
 * 气泡实现复用通用组件 ui/Tooltip（portal + fixed 定位 + 视口夹紧 +
 * role="tooltip" + aria-describedby），避免被设置弹窗的 overflow 裁切。
 */
function ModuleTab(props: {
  tabKey: ViewKey
  label: string
  active: boolean
  tip: ModuleTip
  sections: { definition: string; features: string; scenarios: string }
  onSelect: () => void
}) {
  return (
    <Tooltip
      id={`obs-module-tip-${props.tabKey}`}
      title={props.tip.title}
      rows={[
        { label: props.sections.definition, text: props.tip.definition },
        { label: props.sections.features, text: props.tip.features },
        { label: props.sections.scenarios, text: props.tip.scenarios },
      ]}
    >
      <button
        type="button"
        role="tab"
        aria-selected={props.active}
        className={s(props.active ? 'obs-tab obs-tab--active' : 'obs-tab')}
        onClick={props.onSelect}
      >
        {props.label}
        <span className={s('obs-tab__hint')} aria-hidden="true">
          <Info size={13} strokeWidth={1.5} />
        </span>
      </button>
    </Tooltip>
  )
}

/** 模块开关草稿：后端回报后覆盖；保存前只影响本面板渲染。 */
interface Draft {
  trace: boolean
  metrics: boolean
  replay: boolean
  retentionDays: number
}

const DEFAULT_DRAFT: Draft = {
  trace: true,
  metrics: true,
  replay: true,
  retentionDays: 30,
}

/**
 * 可观测性外壳（2026-11-12；2026-11-16 随独立页面 /observability 自设置中心迁出）：
 * 三个可观测性模块各自持有数据与视图状态，互不 import；外壳只做模块开关与标签切换。
 * 开关经 PUT /settings 持久化，后端即时作用到各模块（独立启停，互不影响）。
 *
 * Session Log（2026-11-13 恢复）是运行时事件台账，与三模块数据源独立，
 * 因此不受开关约束、始终可用，并作为默认视图。
 */
export function ObservabilityPanel() {
  const { t } = useTranslation()
  const settings = useSettingsStore((state) => state.settings)
  const setSettings = useSettingsStore((state) => state.setSettings)
  const [module, setModule] = useState<ViewKey>('session-log')
  const [draft, setDraft] = useState<Draft>(DEFAULT_DRAFT)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null)

  // 后端设置到达后同步草稿（其余设置段由各自面板负责，这里只读 observability）
  const remote = settings?.observability
  useEffect(() => {
    if (remote === undefined) return
    setDraft({
      trace: remote.trace_enabled,
      metrics: remote.metrics_enabled,
      replay: remote.replay_enabled,
      retentionDays: remote.trace_retention_days,
    })
  }, [remote])

  const enabled = useMemo(
    () => ({ trace: draft.trace, metrics: draft.metrics, replay: draft.replay }),
    [draft],
  )
  const visible: ViewKey[] = ['session-log', ...MODULES.filter((key) => enabled[key])]

  // 当前标签被停用时自动落到第一个仍可用的视图（Session Log 永远在首位）
  useEffect(() => {
    const first = visible[0]
    if (first !== undefined && !visible.includes(module)) setModule(first)
  }, [module, visible])

  const toggle = (key: ModuleKey): void => {
    setDraft((prev) => ({ ...prev, [key]: !prev[key] }))
    setStatus(null)
  }

  const save = async (): Promise<void> => {
    setBusy(true)
    setStatus(null)
    try {
      const next = await putSettings({
        observability: {
          trace_enabled: draft.trace,
          trace_retention_days: draft.retentionDays,
          metrics_enabled: draft.metrics,
          replay_enabled: draft.replay,
        },
      })
      setSettings(next)
      setStatus({ ok: true, text: t('observability.modules.saved') })
    } catch (error) {
      setStatus({ ok: false, text: errorMessage(error, t('observability.modules.save_failed')) })
    } finally {
      setBusy(false)
    }
  }

  const sections = {
    definition: t('observability.tips.sections.definition'),
    features: t('observability.tips.sections.features'),
    scenarios: t('observability.tips.sections.scenarios'),
  }
  const tipOf = (key: ViewKey): ModuleTip => ({
    title: t(`observability.tips.${key}.title`),
    definition: t(`observability.tips.${key}.definition`),
    features: t(`observability.tips.${key}.features`),
    scenarios: t(`observability.tips.${key}.scenarios`),
  })

  return (
    <section className={s('obs-panel')} aria-label={t('observability.title')}>
      <header className={s('obs-panel__header')}>
        <div>
          <h3 className={s('obs-panel__title')}>{t('observability.title')}</h3>
          <p className={s('obs-panel__subtitle')}>{t('observability.subtitle')}</p>
        </div>
        <div className={s('obs-tabs')} role="tablist" aria-label={t('observability.title')}>
          {visible.map((key) => (
            <ModuleTab
              key={key}
              tabKey={key}
              label={
                key === 'session-log' ? t('observability.module.session_log') : MODULE_LABEL[key]
              }
              active={module === key}
              tip={tipOf(key)}
              sections={sections}
              onSelect={() => setModule(key)}
            />
          ))}
        </div>
      </header>
      <div className={s('obs-module-switches')}>
        <span className={s('obs-module-switches__title')}>{t('observability.modules.title')}</span>
        {MODULES.map((key) => (
          <label key={key} className={s('obs-check')}>
            <input
              type="checkbox"
              checked={draft[key]}
              onChange={() => toggle(key)}
              aria-label={t(`observability.modules.${key}`)}
            />
            <span>{t(`observability.modules.${key}`)}</span>
          </label>
        ))}
        <label className={s('obs-field')}>
          <span className={s('obs-field__label')}>{t('observability.modules.retention')}</span>
          <input
            type="number"
            min={1}
            max={3650}
            className={s('obs-input obs-input--compact')}
            value={draft.retentionDays}
            disabled={!draft.trace}
            onChange={(event) => {
              const next = Number(event.currentTarget.value)
              if (!Number.isFinite(next)) return
              setDraft((prev) => ({ ...prev, retentionDays: Math.max(1, Math.round(next)) }))
            }}
          />
        </label>
        <button
          type="button"
          className={s('obs-button')}
          disabled={busy}
          onClick={() => void save()}
        >
          {busy ? t('observability.loading') : t('observability.modules.save')}
        </button>
        {status !== null ? (
          <span className={s(status.ok ? 'obs-status' : 'obs-status obs-status--error')}>
            {status.text}
          </span>
        ) : null}
      </div>
      {module === 'session-log' ? <SessionLogPanel /> : null}
      {module === 'trace' && enabled.trace ? <TracePanel /> : null}
      {module === 'metrics' && enabled.metrics ? <MetricsPanel /> : null}
      {module === 'replay' && enabled.replay ? <ReplayPanel /> : null}
    </section>
  )
}
