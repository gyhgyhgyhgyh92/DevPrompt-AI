import './toggle.css'

export interface ToggleProps {
  /** 可访问名（aria-label）；视觉标签由调用方在旁渲染。 */
  label: string
  checked: boolean
  disabled?: boolean
  onChange: (checked: boolean) => void
}

/**
 * 开关控件（F-604）：受控组件，状态与持久化由调用方负责；
 * 用 role=switch 表达开合语义，不承载任何业务判定（MUST-08）。
 */
export function Toggle(props: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={props.checked}
      aria-label={props.label}
      className={props.checked ? 'toggle toggle--checked' : 'toggle'}
      disabled={props.disabled}
      onClick={() => props.onChange(!props.checked)}
    >
      <span className="toggle__thumb" />
    </button>
  )
}
