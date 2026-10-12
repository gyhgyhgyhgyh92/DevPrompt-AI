import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Toggle } from './Toggle'

afterEach(cleanup)

describe('ui/Toggle 控件', () => {
  it('role=switch 且 aria-checked 反映受控状态', () => {
    render(<Toggle label="遥测" checked onChange={() => undefined} />)

    const toggle = screen.getByRole('switch', { name: '遥测' })
    expect(toggle.getAttribute('aria-checked')).toBe('true')
  })

  it('点击回调翻转值；disabled 时不触发', () => {
    const onChange = vi.fn()
    render(<Toggle label="遥测" checked={false} onChange={onChange} />)

    fireEvent.click(screen.getByRole('switch', { name: '遥测' }))
    expect(onChange).toHaveBeenCalledWith(true)

    cleanup()
    render(<Toggle label="遥测" checked disabled onChange={onChange} />)
    fireEvent.click(screen.getByRole('switch', { name: '遥测' }))
    expect(onChange).toHaveBeenCalledTimes(1)
  })
})
