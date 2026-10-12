import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Slider } from './Slider'

afterEach(cleanup)

describe('ui/Slider 控件', () => {
  it('渲染可访问名、取值范围与当前值', () => {
    render(
      <Slider
        label="细节程度"
        value={0.3}
        min={0}
        max={1}
        step={0.01}
        onChange={() => undefined}
      />,
    )

    const slider = screen.getByRole('slider', { name: '细节程度' })
    expect(slider.getAttribute('min')).toBe('0')
    expect(slider.getAttribute('max')).toBe('1')
    expect(slider.getAttribute('step')).toBe('0.01')
    expect((slider as HTMLInputElement).value).toBe('0.3')
    expect(screen.getByText('0.30')).toBeTruthy()
  })

  it('拖动回调数值；disabled 时呈禁用态', () => {
    const onChange = vi.fn()
    render(<Slider label="细节程度" value={0.3} min={0} max={1} step={0.01} onChange={onChange} />)

    fireEvent.change(screen.getByRole('slider', { name: '细节程度' }), { target: { value: '0.6' } })
    expect(onChange).toHaveBeenCalledWith(0.6)

    cleanup()
    render(
      <Slider
        label="细节程度"
        value={0.3}
        min={0}
        max={1}
        step={0.01}
        disabled
        onChange={onChange}
      />,
    )
    expect((screen.getByRole('slider', { name: '细节程度' }) as HTMLInputElement).disabled).toBe(
      true,
    )
  })
})
