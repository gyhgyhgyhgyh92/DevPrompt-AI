import { z } from 'zod'

/** 三模块标准信封（契约见后端 obs_*_routes.py）。 */
export const ObsListSchema = z.object({
  items: z.array(z.record(z.string(), z.unknown())),
  schema_version: z.number().default(1),
})

export const ObsEventPageSchema = z.object({
  items: z.array(z.record(z.string(), z.unknown())),
  has_more: z.boolean(),
  next_cursor: z.number().int(),
  schema_version: z.number().default(1),
})

export const ObsTraceTreeSchema = z.object({
  trace_id: z.string(),
  items: z.array(z.record(z.string(), z.unknown())),
  schema_version: z.number().default(1),
})

export const ObsEventSchema = z.object({
  event: z.record(z.string(), z.unknown()).nullable(),
  schema_version: z.number().default(1),
})

export const ObsMetricSummarySchema = z.object({
  items: z.array(z.record(z.string(), z.unknown())),
  schema_version: z.number().default(1),
})

export const ObsAlertsSchema = z.object({
  items: z.array(z.record(z.string(), z.unknown())),
  limit: z.number().int(),
  offset: z.number().int(),
  schema_version: z.number().default(1),
})

export const ObsMetricsConfigSchema = z.object({
  config: z.record(z.string(), z.unknown()),
  schema_version: z.number().default(1),
})

export const ObsReplayRunSchema = z.object({
  run: z.record(z.string(), z.unknown()),
  nodes: z.array(z.record(z.string(), z.unknown())),
  schema_version: z.number().default(1),
})

export const ObsReplayCompareSchema = z.object({
  nodes: z.array(z.record(z.string(), z.unknown())),
  final: z.record(z.string(), z.unknown()),
  schema_version: z.number().default(1),
})

export type ObsListItem = z.infer<typeof ObsListSchema>['items'][number]
export type ObsEventItem = ObsListItem
export type ObsReplayNode = z.infer<typeof ObsReplayRunSchema>['nodes'][number]
