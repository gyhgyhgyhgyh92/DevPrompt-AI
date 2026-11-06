import { useTranslation } from 'react-i18next'

export interface ApiModeSelectProps {
  /** 该 provider 支持的模式集（后端目录的 supported_api_modes）。 */
  supported: ReadonlyArray<string> | undefined
  /** 当前 api_mode（空 = 按 provider 默认推断）。 */
  value: string
  /** provider 的默认模式，用于展示「默认」选项的说明。 */
  defaultMode: string
  onModeChange: (mode: string) => void
  /** 与外层 label 关联的 id；多条目并存时必须逐条不同，否则 label 只关联第一条。 */
  id?: string
  disabled?: boolean
}

/**
 * API 形态选择（2026-09-17 多供应商扩展 W8）。
 *
 * **可选值来自后端目录** `supported_api_modes`——前端不内置模式清单，
 * 否则新增 provider 时下拉会列出它其实不支持的形态。
 *
 * 2026-10-18：思考强度与上下文窗口档位已迁到启动页的模型下拉（按模型粒度配置，
 * 档位由厂商 `/models` 实时同步），本组件只保留 API 形态。
 */
export function ApiModeSelect({
  supported,
  value,
  defaultMode,
  onModeChange,
  id,
  disabled,
}: ApiModeSelectProps) {
  const { t } = useTranslation()
  const list = (supported ?? []).length > 0 ? (supported ?? []) : [defaultMode]
  // 未传 id 时回落到固定值：label 的 htmlFor 不能为空，否则控件失去关联（可访问性）
  const selectId = id ?? 'model-api-mode'
  // 只有一种形态时不渲染下拉：「默认（X）」+「X」两项指向同一个值，是纯冗余。
  // 多数第三方厂商确实只有 OpenAI 兼容形态（model_spec 逐家核实），如实说明即可。
  if (list.length <= 1) {
    return (
      <div className="model-api-mode">
        <div className="settings-field">
          <span className="settings-label">{t('settings.api_mode')}</span>
          <p className="settings-hint">{t('settings.api_mode_only', { mode: list[0] })}</p>
        </div>
      </div>
    )
  }
  return (
    <div className="model-api-mode">
      <div className="settings-field">
        <label className="settings-label" htmlFor={selectId}>
          API 形态
        </label>
        <select
          id={selectId}
          className="settings-select"
          value={value}
          disabled={disabled}
          onChange={(event) => onModeChange(event.currentTarget.value)}
        >
          <option value="">默认（{defaultMode}）</option>
          {list.map((mode) => (
            <option key={mode} value={mode}>
              {mode}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}
