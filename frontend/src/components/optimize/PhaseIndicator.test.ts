import { cleanup, render, screen } from '@testing-library/react'
import { createElement } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { PhaseIndicator } from './PhaseIndicator'

afterEach(cleanup)

describe('PhaseIndicator 状态镜像', () => {
  it('高亮当前态并给已完成态打勾（只渲染后端 state，MUST-07）', () => {
    render(createElement(PhaseIndicator, { state: 'ASKING' }))

    const current = screen.getByRole('listitem', { current: 'step' })
    expect(current.textContent).toBe('ASKING')
    expect(screen.getByText('✓ INIT')).toBeTruthy()
    expect(screen.getByText('✓ PROBING')).toBeTruthy()
  })

  it('未知状态不高亮任何步进（镜像展示，不做转移判定）', () => {
    render(createElement(PhaseIndicator, { state: 'SOMETHING' }))

    expect(screen.queryByRole('listitem', { current: 'step' })).toBeNull()
  })
})
