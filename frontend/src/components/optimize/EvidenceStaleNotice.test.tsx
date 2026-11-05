import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { EvidenceStaleNotice } from './EvidenceStaleNotice'

afterEach(cleanup)

describe('EvidenceStaleNotice', () => {
  it('未过期时不渲染任何内容', () => {
    render(<EvidenceStaleNotice stale={false} />)

    expect(screen.queryByRole('status')).toBeNull()
  })

  it('过期时给出可操作的提示', () => {
    render(<EvidenceStaleNotice stale />)

    expect(screen.getByRole('status').textContent).toContain('方案基于上一轮取证结果')
  })
})
