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

export interface ContextWindowHintProps {
  /** 条目级覆盖值（为空表示沿用 provider 默认）。 */
  entryWindow: number | null | undefined
  /** provider 默认窗口。 */
  providerWindow: number | null | undefined
}

const WINDOW_TIERS = [
  { tokens: 32000, label: '32K' },
  { tokens: 128000, label: '128K' },
  { tokens: 200000, label: '200K' },
  { tokens: 1000000, label: '1M' },
]

/**
 * 上下文窗口**只读展示**（2026-09-17 W8）。
 *
 * 刻意**不做自动截断**：截断检索证据会削弱候选集信息量，而召回率 ≥80% 是 MUST-25
 * 硬门禁——用截断换窗口是牺牲更重要的指标。超出时仅提示，由用户自行决定是否
 * 补充组件名以减少证据量。
 */
export function ContextWindowHint({ entryWindow, providerWindow }: ContextWindowHintProps) {
  const effective = entryWindow ?? providerWindow
  const shown = formatWindow(effective)
  if (shown === null) return null
  return (
    <span className="settings-hint">
      上下文窗口 {shown}
      {entryWindow == null && providerWindow != null ? '（厂商默认）' : '（本条目覆盖）'}
      {' · '}
      {WINDOW_TIERS.map((tier) => tier.label).join(' / ')} 参考档位
    </span>
  )
}
