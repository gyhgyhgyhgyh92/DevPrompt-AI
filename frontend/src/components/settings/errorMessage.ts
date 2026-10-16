import { ERROR_TEXT, SUCCESS_CODE } from '../../schemas/errorCodes'
import type { ApiError } from '../../api/errors'

/**
 * 错误文案三段降级（N-7）：
 *   ①按 code 查文案表 →②未命中回落后端 message →③仍无则用fallback。
 *
 * 为什么不查表就用 message：后端 message 是**给日志看的**，含上下文与技术细节
 * （如 output_type 名、路径片段），直接展示既不友好也可能泄漏实现（MUST-19）。
 * 保留 message 作为第二段是为了向前兼容——新后端码上线而前端尚未更新时，
 * 用户仍能看到后端给的可操作描述，而不是一句「未知错误」。
 *
 * 降级链借鉴 prompt-optimizer 的 `getI18nErrorMessage`（packages/ui/src/utils/error.ts）。
 */
export function errorMessage(error: unknown, fallback: string): string {
  const fromTable = lookupByCode(error)
  if (fromTable !== '') return fromTable
  if (error instanceof Error && error.message !== '') return error.message
  return fallback
}

/** 契约破坏 / 网络 / 超时 / 中止：前端侧错误，按 kind 归类而非按 code（哨兵码为负）。 */
const KIND_TEXT: Readonly<Record<string, string>> = {
  contract: '服务返回的数据不符合契约，请稍后重试',
  network: '网络连接失败，请检查网络后重试',
  timeout: '请求超时，请稍后重试',
  aborted: '请求已取消',
}

/** 按 code 查表；未命中再按 ApiError.kind 查；都没有则返回空串表示「需回落」。 */
function lookupByCode(error: unknown): string {
  if (typeof error !== 'object' || error === null) return ''
  const candidate = error as { code?: unknown; kind?: unknown }
  if (typeof candidate.code === 'number' && candidate.code !== SUCCESS_CODE) {
    const text = ERROR_TEXT[candidate.code]
    if (text !== undefined) return text
  }
  if (typeof candidate.kind === 'string') {
    return KIND_TEXT[candidate.kind] ?? ''
  }
  return ''
}

/** 错误是否已被文案表覆盖（供 M-10 静态检查与测试断言复用）。 */
export function hasMappedText(code: number): boolean {
  return Object.prototype.hasOwnProperty.call(ERROR_TEXT, code)
}

export type { ApiError }
