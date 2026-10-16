import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { ModelCapabilityBadge } from './ModelCapabilityBadge'
import { ModelParamEditor } from './ModelParamEditor'
import type { ParameterDefinition } from '../../schemas/modelSpec'

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

const NUMBER_DEF: ParameterDefinition = {
  name: 'temperature',
  type: 'number',
  label: '随机性',
  description: '越高越发散',
  default_value: 0.3,
  min_value: 0,
  max_value: 2,
  step: 0.1,
  allowed_values: [],
  unit: '',
  is_native: true,
}

const BOOL_DEF: ParameterDefinition = {
  ...NUMBER_DEF,
  name: 'stream',
  type: 'boolean',
  label: '流式',
}

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
})

describe('ModelParamEditor', () => {
  it('数值参数渲染为滑条并透传变更', () => {
    const onChange = vi.fn()
    render(
      <ModelParamEditor
        definitions={[NUMBER_DEF]}
        value={{ temperature: 0.5 }}
        onChange={onChange}
      />,
    )
    const slider = screen.getByLabelText('随机性') as HTMLInputElement
    expect(slider.type).toBe('range')
    // 范围严格来自后端定义
    expect(slider.min).toBe('0')
    expect(slider.max).toBe('2')
    fireEvent.change(slider, { target: { value: '1.2' } })
    expect(onChange).toHaveBeenCalledWith({ temperature: 1.2 })
  })

  it('布尔参数渲染为开关', () => {
    const onChange = vi.fn()
    render(<ModelParamEditor definitions={[BOOL_DEF]} value={{}} onChange={onChange} />)
    const box = screen.getByLabelText('流式') as HTMLInputElement
    expect(box.type).toBe('checkbox')
    fireEvent.click(box)
    expect(onChange).toHaveBeenCalledWith({ stream: true })
  })

  it('整数参数按 step=1 取整', () => {
    const onChange = vi.fn()
    const intDef: ParameterDefinition = {
      ...NUMBER_DEF,
      name: 'max_tokens',
      type: 'integer',
      label: '最大输出',
      min_value: 1,
      max_value: 4096,
      step: 1,
      default_value: 1024,
    }
    render(<ModelParamEditor definitions={[intDef]} value={{}} onChange={onChange} />)
    const slider = screen.getByLabelText('最大输出') as HTMLInputElement
    fireEvent.change(slider, { target: { value: '2.4' } })
    expect(onChange).toHaveBeenCalledWith({ max_tokens: 2 })
  })

  it('字符串参数渲染为输入框并展示说明', () => {
    const onChange = vi.fn()
    const strDef: ParameterDefinition = {
      ...NUMBER_DEF,
      name: 'reasoning_effort',
      type: 'string',
      label: '推理强度',
      allowed_values: ['low', 'high'],
    }
    render(<ModelParamEditor definitions={[strDef]} value={{}} onChange={onChange} />)
    expect(screen.getByLabelText('推理强度')).toBeTruthy()
    expect(screen.getByText('越高越发散')).toBeTruthy()
  })

  it('未设值时回退到后端给的 default_value', () => {
    render(<ModelParamEditor definitions={[NUMBER_DEF]} value={{}} onChange={vi.fn()} />)
    expect(screen.getByText('0.30')).toBeTruthy()
  })

  it('无定义时给出提示而非空白', () => {
    render(<ModelParamEditor definitions={[]} value={{}} onChange={vi.fn()} />)
    expect(screen.getByText(/暂无可调参数/)).toBeTruthy()
  })

  it('值变更后受控同步', () => {
    const { rerender } = render(
      <ModelParamEditor
        definitions={[NUMBER_DEF]}
        value={{ temperature: 0.5 }}
        onChange={vi.fn()}
      />,
    )
    rerender(
      <ModelParamEditor
        definitions={[NUMBER_DEF]}
        value={{ temperature: 1.5 }}
        onChange={vi.fn()}
      />,
    )
    expect(screen.getByText('1.50')).toBeTruthy()
  })
})
