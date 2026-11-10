import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { ModelCapabilityBadge } from './ModelCapabilityBadge'

/**
 * 组件测试（2026-09-17 模型管理迁移）。
 *
 * 关注两条铁律：
 * 1. **控件由后端定义驱动** —— 数值渲染滑条、布尔渲染开关，其余渲染输入框；
 *    前端不得内置第二份范围/枚举（改了 definitions 渲染就该跟着变）。
 * 2. **不做业务判定** —— 前端只透传取值，校验结论由后端给出（MUST-08）。
 */

// DOM 跨用例不隔离会��� getByText 命中多个元素，故每例后清理
afterEach(cleanup)

describe('ModelCapabilityBadge', () => {
  it('三态徽标全部渲染', () => {
    render(
      <ModelCapabilityBadge
        capabilities={{
          supports_tools: true,
          supports_reasoning: false,
          max_context_length: 64000,
        }}
      />,
    )
    expect(screen.getByText('工具调用')).toBeTruthy()
    expect(screen.getByText('推理')).toBeTruthy()
    expect(screen.getByText(/上下文 64K/)).toBeTruthy()
  })

  it('不支持的能力带删除线样式（不隐藏，如实呈现）', () => {
    render(
      <ModelCapabilityBadge
        capabilities={{
          supports_tools: false,
          supports_reasoning: false,
          max_context_length: null,
        }}
      />,
    )
    expect(screen.getByText('工具调用').className).toContain('--off')
    expect(screen.getByText(/上下文 未知/)).toBeTruthy()
  })

  it('百万级上下文格式化正确', () => {
    render(
      <ModelCapabilityBadge
        capabilities={{
          supports_tools: true,
          supports_reasoning: true,
          max_context_length: 1_000_000,
        }}
      />,
    )
    expect(screen.getByText(/上下文 1M/)).toBeTruthy()
  })

  it('二进制档位显示为 256K，不四舍五入成 262K、也不带精确值', () => {
    render(
      <ModelCapabilityBadge
        capabilities={{
          supports_tools: true,
          supports_reasoning: true,
          max_context_length: 262_144,
        }}
      />,
    )
    expect(screen.getByText(/上下文 256K/)).toBeTruthy()
    expect(screen.queryByText(/262,144/)).toBeNull()
  })
})
