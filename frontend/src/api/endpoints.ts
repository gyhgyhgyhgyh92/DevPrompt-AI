import { API_BASE_URL } from './client'

/** 端点清单（与仓库根 openapi.json 的 paths 一一对应；新增端点必须先冻结契约）。 */
export const ENDPOINTS = {
  health: `${API_BASE_URL}/health`,
  optimize: `${API_BASE_URL}/optimize`,
  progress: (flowId: string) => `${API_BASE_URL}/progress/${flowId}`,
  followup: (flowId: string) => `${API_BASE_URL}/followup/${flowId}`,
  result: (flowId: string) => `${API_BASE_URL}/result/${flowId}`,
  feedback: `${API_BASE_URL}/feedback`,
  preference: `${API_BASE_URL}/preference`,
  history: `${API_BASE_URL}/history`,
  projectScan: `${API_BASE_URL}/project/scan`,
  settings: `${API_BASE_URL}/settings`,
} as const
