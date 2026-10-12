/**
 * API 错误（MUST-19：错误响应仅含 code + message + request_id，不回传堆栈）。
 * Zod 校验失败也归一到本类型，调用方不重试（MUST-15：属契约破坏）。
 */
export class ApiError extends Error {
  readonly code: number
  readonly requestId: string

  constructor(code: number, message: string, requestId: string) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.requestId = requestId
  }
}
