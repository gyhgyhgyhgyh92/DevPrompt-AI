import { formatWindow } from './ProviderSelect'

export interface ApiModeSelectProps {
  /** 该 provider 支持的模式集（后端目录的 supported_api_modes）。 */
  supported: ReadonlyArray<string> | undefined
  /** 当前 api_mode（空 = 按 provider 默认推断）。 */
  value: string
  /** provider 的默认模式，用于展示「默认」选项的说明。 */
  defaultMode: string
  /** 该 provider 是否支持推理（决定是否显示思考强度）。 */
  supportsReasoning: boolean
  reasoningEffort: string
  onModeChange: (mode: string) => void
  onEffortChange: (effort: string) => void
  disabled?: boolean
}

/** 思考强度取值。六值覆盖 OpenAI(minimal~high)、grok(none) 与「不设置」。 */
export const REASONING_EFFORTS = [
  { value: '', label: '默认（不设置）' },
  { value: 'minimal', label: 'minimal · 最省' },
  { value: 'low', label: 'low · 低' },
  { value: 'medium', label: 'medium · 中' },
  { value: 'high', label: 'high · 高' },
  { value: 'none', label: 'none · 关闭推理' },
]

/**
 * API 形态 + 思考强度选择（2026-09-17 多供应商扩展 W8）。
 *
 * 两点必须诚实呈现（承接上一轮「force_params 不下发就收紧」的同一口径）：
 * 1. **可选值来自后端目录** `supported_api_modes`——前端不内置模式清单，
 *    否则新增 provider 时下拉会列出它其实不支持的形态。
 * 2. **不可用的选项禁用而非隐藏**——用户能看见「有这个形态但本厂商不支持」，
 *    避免困惑为什么下拉里没有。
 */
export function ApiModeSelect({
  supported,
  value,
  defaultMode,
  supportsReasoning,
  reasoningEffort,
  onModeChange,
  onEffortChange,
  disabled,
}: ApiModeSelectProps) {
  const list = (supported ?? []).length > 0 ? (supported ?? []) : [defaultMode]
  return (
    <div className="model-api-mode">
      <div className="settings-field">
        <label className="settings-label" htmlFor="model-api-mode">
          API 形态
        </label>
        <select
          id="model-api-mode"
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
      {supportsReasoning ? (
        <div className="settings-field">
          <label className="settings-label" htmlFor="model-reasoning-effort">
            思考强度
          </label>
          <select
            id="model-reasoning-effort"
            className="settings-select"
            value={reasoningEffort}
            disabled={disabled}
            onChange={(event) => onEffortChange(event.currentTarget.value)}
          >
            {REASONING_EFFORTS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>
      ) : null}
    </div>
  )
}

export interface ContextWindowSelectProps {
  /** 当前选中的档位（null/undefined = 沿用厂商默认）。 */
  value: number | null | undefined
  /** 厂商标称窗口；null/undefined = **未登记**（此时整块不渲染）。 */
  vendorWindow: number | null | undefined
  /** 厂商给出的可选档位集合（绝对 token，升序）；空 = 只能沿用默认。 */
  tiers: ReadonlyArray<number>
  onChange: (value: number | null) => void
  disabled?: boolean
}

/**
 * 上下文窗口**档位单选**（2026-09-17 B3）。
 *
 * 三条设计约束（缺一不可）：
 * 1. **只能从厂商给出的档位里选**，不提供自由输入——自由填数会让用户填出
 *    「我设了 1M 但实际只有 200K」的假安全感；
 * 2. **未登记则不渲染**：厂商窗口查证不到时显示空档位，比显示一个占位数字诚实；
 * 3. **只改告警预算，不做截断**：截断检索证据会削弱召回率，而召回率 ≥80% 是
 *    MUST-25 硬门禁——用截断换窗口是牺牲更重要的指标。
 */
export function ContextWindowSelect({
  value,
  vendorWindow,
  tiers,
  onChange,
  disabled,
}: ContextWindowSelectProps) {
  if (vendorWindow == null) return null
  const options = tiers.length > 0 ? tiers : [vendorWindow]
  const current = value ?? vendorWindow
  return (
    <div className="settings-field">
      <label className="settings-label" htmlFor="model-context-window">
        上下文窗口
      </label>
      <select
        id="model-context-window"
        className="settings-select"
        value={String(current)}
        disabled={disabled || options.length <= 1}
        onChange={(event) => {
          const picked = Number(event.currentTarget.value)
          // 选中厂商标称值即回落到「跟随厂商」，避免冗余状态
          onChange(picked === vendorWindow ? null : picked)
        }}
      >
        {options.map((tier) => (
          <option key={tier} value={String(tier)}>
            {formatWindow(tier) ?? String(tier)}
            {tier === vendorWindow ? '（厂商标称）' : ''}
          </option>
        ))}
      </select>
      <span className="settings-hint">
        仅用于超限提示，不截断证据；超出时建议补充组件名以减少检索量
      </span>
    </div>
  )
}
