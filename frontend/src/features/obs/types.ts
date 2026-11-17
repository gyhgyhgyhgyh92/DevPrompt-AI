/** 回放时间轴上的一个事件点（纯展示类型；数据来自 Trace 模块的标准事件契约）。 */
export interface TraceTimelinePoint {
  seq: number
  type: string
  ts: string
  run_id: string
  label: string
  phase: string
  duration_ms: number | null
}
