import { describe, expect, it } from 'vitest'
import {
  abortedError,
  businessError,
  contractError,
  httpError,
  networkError,
  timeoutError,
} from '../../api/errors'
import { errorMessage, hasMappedText } from './errorMessage'
import { ERROR_TEXT } from '../../schemas/errorCodes'

/**
 * 错误文案三段降级（N-7）：按 code 查表 → 后端 message → fallback。
 *
 * 关注两件事：①精确文案确实优先于后端原始 message；②降级链不产生「未知错误」
 * 这种死胡同——新后端码上线而前端未更新时，用户仍看到可操作描述。
 */
describe('errorMessage 三段降级', () => {
  it('命中映射表时用本地文案，不展示后端原始 message', () => {
    const err = businessError(
      5013,
      'LLM 两次输出均无法解析，output_type=MultiVariantDraft',
      'rid-1',
    )
    const text = errorMessage(err, '请求失败')
    expect(text).toBe(ERROR_TEXT[5013])
    expect(text).toContain('余额')
    expect(text).not.toContain('output_type') // 不得泄漏实现细节
  })

  it('未知 code 回落后端 message', () => {
    //9999 后端存在、前端未映射（新码上线但前端未更新）
    const err = businessError(9999, '后端给的可操作描述', 'rid-2')
    expect(errorMessage(err, '请求失败')).toBe('后端给的可操作描述')
  })

  it('后端 message 为空时回落 fallback', () => {
    const err = businessError(9998, '', 'rid-3')
    expect(errorMessage(err, '请求失败')).toBe('请求失败')
  })

  it('非 Error 值直接用 fallback', () => {
    expect(errorMessage(null, '请求失败')).toBe('请求失败')
    expect(errorMessage(undefined, '请求失败')).toBe('请求失败')
    expect(errorMessage('字符串错误', '请求失败')).toBe('请求失败')
    expect(errorMessage(42, '请求失败')).toBe('请求失败')
  })

  it('传输层错误按 kind 归类，而非依赖负数哨兵码', () => {
    expect(errorMessage(networkError('x'), 'F')).toContain('网络')
    expect(errorMessage(timeoutError('r'), 'F')).toContain('超时')
    expect(errorMessage(abortedError('r'), 'F')).toContain('取消')
    expect(errorMessage(contractError('x', 'r'), 'F')).toContain('契约')
  })

  it('HTTP 非 2xx 展示状态码，不误报为网络故障', () => {
    // 405 常见于「后端未重启、新路由未加载」，说成网络问题会把人带偏
    const text = errorMessage(httpError(405, '流式端点不可用'), 'F')
    expect(text).toContain('405')
    expect(text).not.toContain('网络连接失败')
  })

  it('成功码不被当作错误展示', () => {
    expect(errorMessage({ code: 0 }, 'F')).toBe('F')
  })

  it('hasMappedText 供检查与测试复用', () => {
    expect(hasMappedText(2005)).toBe(true)
    expect(hasMappedText(9999)).toBe(false)
  })
})

describe('映射表内容', () => {
  it('每个码都有非空中文文案', () => {
    for (const [code, text] of Object.entries(ERROR_TEXT)) {
      expect(text.trim(), `码 ${code} 文案为空`).not.toBe('')
      expect(text, `码 ${code} 文案非中文`).toMatch(/[一-龥]/)
    }
  })

  it('不泄漏内部标识符或路径', () => {
    for (const [code, text] of Object.entries(ERROR_TEXT)) {
      expect(text, `码 ${code} 文案含 src/ 路径`).not.toContain('src/')
      expect(text.toLowerCase(), `码 ${code} 文案含变量名风格`).not.toMatch(/output_type/)
    }
  })
})
