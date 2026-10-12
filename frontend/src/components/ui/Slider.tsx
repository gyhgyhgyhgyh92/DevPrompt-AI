import type { ChangeEvent } from 'react'
import './slider.css'

export interface SliderProps {
  /** 可访问名（aria-label）；视觉标签同名渲染。 */
  label: string
  value: number
  min: number
  max: number
  step: number
  disabled?: boolean
  onChange: (value: number) => void
}

/**
 * 数值滑条（F-604）：受控组件，只做取值传递；
 * 不做任何推荐/置信度判定（MUST-08），取值合法性由后端兜底。
 */
export function Slider(props: SliderProps) {
  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    props.onChange(Number(event.currentTarget.value))
  }

  return (
    <label className="slider">
      <span className="slider__label">{props.label}</span>
      <input
        className="slider__input"
        type="range"
        aria-label={props.label}
        min={props.min}
        max={props.max}
        step={props.step}
        value={props.value}
        disabled={props.disabled}
        onChange={handleChange}
      />
      <output className="slider__value">{props.value.toFixed(2)}</output>
    </label>
  )
}
