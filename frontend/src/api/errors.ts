/**
 * API 错误与错误映射（MUST-19：错误响应仅含 code + message + request_id，不回传堆栈）。
 * 所有失败路径（业务码、契约破坏、网络/超时/中止）统一映射为 ApiError；调用方不重试（MUST-15）。
 */

/** 错误分类：business=信封业务码；contract=契约破坏；其余为传输层。 */
export type ApiErrorKind = 'business' | 'contract' | 'network' | 'timeout' | 'aborted'

/** 契约信封成功码：等于它才取 data（错误映射基准）。 */
export const SUCCESS_CODE = 0

/** 非业务错误的哨兵 code（与后端业务码区间不重叠；分类以 kind 为准）。 */
const SENTINEL_CODE: Record<Exclude<ApiErrorKind, 'business'>, number> = {
  contract: -1,
  network: -2,
  timeout: -3,
  aborted: -4,
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind
  readonly code: number
  readonly requestId: string

  constructor(
    kind: ApiErrorKind,
    code: number,
    message: string,
    requestId: string,
    options?: { cause?: unknown },
  ) {
    super(message, options)
    this.name = 'ApiError'
    this.kind = kind
    this.code = code
    this.requestId = requestId
  }
}

/** 业务错误：code/message 来自后端信封（如 6001/6003 状态错误、9002 配置错误）。 */
export function businessError(code: number, message: string, requestId: string): ApiError {
  return new ApiError('business', code, message, requestId)
}

/** 契约破坏（信封畸形 / Zod 校验失败 / 请求体不合法）：重试只会复现失败。 */
export function contractError(message: string, requestId: string, cause?: unknown): ApiError {
  return new ApiError('contract', SENTINEL_CODE.contract, message, requestId, { cause })
}

/** 网络层失败（fetch 拒绝且非中止）。 */
export function networkError(message: string, cause?: unknown): ApiError {
  return new ApiError('network', SENTINEL_CODE.network, message, '', { cause })
}

/** 超时中止（外部调用必须设超时）。 */
export function timeoutError(requestId: string): ApiError {
  return new ApiError('timeout', SENTINEL_CODE.timeout, '请求超时', requestId)
}

/** 调用方主动中止。 */
export function abortedError(requestId: string): ApiError {
  return new ApiError('aborted', SENTINEL_CODE.aborted, '请求已中止', requestId)
}
