import { cleanup, render, screen } from '@testing-library/react'
import { createElement } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { ContextPanel } from './ContextPanel'

afterEach(cleanup)

describe('ContextPanel 只读渲染', () => {
  it('渲染目标定位、取证事实（key + passed 标记 + evidence）与 L3 偏好条', () => {
    render(
      createElement(ContextPanel, {
        target: { name: 'build', path: 'src/app.py', line: 12 },
        facts: [
          { key: 'fact_a', passed: true, evidence: '定位到 build' },
          { key: 'fact_b', passed: false, evidence: '共 3 处调用' },
        ],
        vector: {
          detail_level: 0.25,
          include_diff: 0.75,
          specify_tests: 0.1,
          max_files_norm: 0.9,
        },
      }),
    )

    expect(screen.getByText('build@src/app.py:12')).toBeTruthy()
    expect(screen.getByText('fact_a')).toBeTruthy()
    expect(screen.getByText('fact_b')).toBeTruthy()
    expect(screen.getByText('✓')).toBeTruthy()
    expect(screen.getByText('✗')).toBeTruthy()
    expect(screen.getByText('定位到 build')).toBeTruthy()
    expect(screen.getByText('共 3 处调用')).toBeTruthy()
    expect(screen.getByText('detail_level')).toBeTruthy()
    expect(screen.getByText('25%')).toBeTruthy()
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(screen.queryByRole('slider')).toBeNull()
    expect(screen.queryByRole('checkbox')).toBeNull()
  })

  it('line 为 0 时不显示行号', () => {
    render(
      createElement(ContextPanel, {
        target: { name: 'build', path: 'src/app.py', line: 0 },
        facts: [],
        vector: null,
      }),
    )

    expect(screen.getByText('build@src/app.py')).toBeTruthy()
    expect(screen.queryByText(/build@src\.app\.py:/)).toBeNull()
  })

  it('数据缺位时渲染空态文案', () => {
    render(createElement(ContextPanel, { target: null, facts: [], vector: null }))

    expect(screen.getByText('暂无目标定位')).toBeTruthy()
    expect(screen.getByText('暂无取证事实')).toBeTruthy()
    expect(screen.getByText('暂无偏好数据')).toBeTruthy()
  })
})
