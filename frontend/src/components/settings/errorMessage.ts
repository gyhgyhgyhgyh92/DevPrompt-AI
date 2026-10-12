/** 错误展示只取 message（MUST-19：不渲染堆栈）；非 Error 统一兜底文案。 */
export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message !== '' ? error.message : fallback
}
