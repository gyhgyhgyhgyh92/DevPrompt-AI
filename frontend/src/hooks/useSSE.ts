/**
 * SSE 订阅（GET /progress/{flow_id}）。
 * MUST-15：EventSource.close() 必须写在 effect cleanup；断流不自动重连，由业务层显式决定。
 */
export function useSSE(): void {}
