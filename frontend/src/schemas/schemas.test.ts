import { describe, expect, it } from 'vitest'
import {
  FeedbackRequestSchema,
  FlowSnapshotSchema,
  FollowupRequestSchema,
  RankingViewSchema,
  VariantSchema,
} from './optimize'
import { PagedHistoryItemSchema, PreferenceVectorSchema } from './preference'
import { ModelServiceUpdateSchema, SettingsResponseSchema } from './settings'

describe('schemas/optimize 契约校验', () => {
  it('FollowupRequest 三模式各自合法', () => {
    expect(
      FollowupRequestSchema.safeParse({ answers: { target: 'Foo' }, escape: false }).success,
    ).toBe(true)
    expect(FollowupRequestSchema.safeParse({ escape: true }).success).toBe(true)
    expect(
      FollowupRequestSchema.safeParse({ escape: false, guardrail_action: 'continue' }).success,
    ).toBe(true)
  })

  it('FollowupRequest 三模式互斥：任意混用均拒绝', () => {
    expect(
      FollowupRequestSchema.safeParse({ answers: { target: 'Foo' }, escape: true }).success,
    ).toBe(false)
    expect(
      FollowupRequestSchema.safeParse({ escape: true, guardrail_action: 'generate' }).success,
    ).toBe(false)
    expect(
      FollowupRequestSchema.safeParse({
        answers: { target: 'Foo' },
        escape: false,
        guardrail_action: 'continue',
      }).success,
    ).toBe(false)
  })

  it('FlowSnapshotSchema 接受最小快照，可选字段缺省', () => {
    const parsed = FlowSnapshotSchema.safeParse({
      session_id: 'sess-1',
      state: 'INIT',
      status: 'ask',
      message: '',
    })
    expect(parsed.success).toBe(true)
  })

  it('FlowSnapshotSchema 拒绝畸形快照', () => {
    expect(
      FlowSnapshotSchema.safeParse({ state: 'INIT', status: 'ask', message: '' }).success,
    ).toBe(false)
    expect(
      FlowSnapshotSchema.safeParse({ session_id: 's', state: 'INIT', status: 'ask', variants: 'x' })
        .success,
    ).toBe(false)
    expect(
      FlowSnapshotSchema.safeParse({
        session_id: 's',
        state: 'INIT',
        status: 'ask',
        message: '',
        questions: [{ key: 'target' }],
      }).success,
    ).toBe(false)
  })

  it('FlowSnapshotSchema 接受 target/facts 载荷', () => {
    const parsed = FlowSnapshotSchema.safeParse({
      session_id: 's',
      state: 'PROBING',
      status: 'ask',
      message: '',
      target: { name: 'build', path: 'src/app.py', line: 12 },
      facts: [{ key: 'fact_a', passed: true, evidence: '定位到 build' }],
    })
    expect(parsed.success).toBe(true)
  })

  it('FlowSnapshotSchema 拒绝畸形 target/facts', () => {
    expect(
      FlowSnapshotSchema.safeParse({
        session_id: 's',
        state: 'PROBING',
        status: 'ask',
        message: '',
        target: { name: 'build', path: 'src/app.py', line: '12' },
      }).success,
    ).toBe(false)
    expect(
      FlowSnapshotSchema.safeParse({
        session_id: 's',
        state: 'PROBING',
        status: 'ask',
        message: '',
        facts: [{ key: 'fact_a', passed: 'yes', evidence: 'x' }],
      }).success,
    ).toBe(false)
  })

  it('RankingView / Variant 载荷字段类型不匹配即拒绝', () => {
    expect(
      RankingViewSchema.safeParse({
        confidence: 'high',
        fit: 1,
        gap: 1,
        marked: true,
        reason: '',
        total: 1,
        variant: 'A',
      }).success,
    ).toBe(false)
    expect(VariantSchema.safeParse({ body: '', level: 'A' }).success).toBe(false)
  })

  it('FeedbackRequest variant 超出 A/B/C 档位即拒绝', () => {
    expect(
      FeedbackRequestSchema.safeParse({ session_id: 's', action: 'adopt', variant: 'D' }).success,
    ).toBe(false)
  })
})

describe('schemas/preference 与 settings 契约校验', () => {
  it('PreferenceVector 四维必须是数字', () => {
    expect(
      PreferenceVectorSchema.safeParse({
        detail_level: 0.25,
        include_diff: 0.75,
        specify_tests: 'x',
        max_files_norm: 0.9,
      }).success,
    ).toBe(false)
  })

  it('PagedHistoryItem 元素缺字段即拒绝', () => {
    expect(
      PagedHistoryItemSchema.safeParse({
        items: [{ session_id: 's', state: 'DONE', project: 'p' }],
        has_more: false,
        limit: 50,
        offset: 0,
      }).success,
    ).toBe(false)
  })

  it('PagedHistoryItem 缺少分页字段即拒绝（契约四字段必填）', () => {
    expect(
      PagedHistoryItemSchema.safeParse({
        items: [],
        has_more: false,
        limit: 50,
      }).success,
    ).toBe(false)
  })

  it('SettingsResponse 拒绝类型不匹配与缺锁定项', () => {
    const base = {
      models: [],
      model_service: {
        api_key_masked: 'sk-••••3f7a',
        base_url: '',
        model_id: 'demo',
        provider: 'DeepSeek',
        timeout: 60,
      },
      process: {
        followup_cost_budget: 1,
        followup_soft_round_guard: 10,
        telemetry: true,
      },
      locked: { candidate_limit: 25 },
    }
    expect(SettingsResponseSchema.safeParse(base).success).toBe(true)
    expect(
      SettingsResponseSchema.safeParse({
        ...base,
        process: { ...base.process, telemetry: 'yes' },
      }).success,
    ).toBe(false)
    expect(SettingsResponseSchema.safeParse({ ...base, locked: {} }).success).toBe(false)
  })

  it('ModelServiceSettings.provider 为必填字符串（缺 models 亦判失败）', () => {
    expect(
      SettingsResponseSchema.safeParse({
        models: [],
        model_service: {
          api_key_masked: '',
          base_url: '',
          model_id: 'demo',
          timeout: 60,
        },
        process: {
          followup_cost_budget: 1,
          followup_soft_round_guard: 10,
          telemetry: true,
        },
        locked: { candidate_limit: 25 },
      }).success,
    ).toBe(false)
  })

  it('ModelServiceUpdate.provider 可省略或为 null（None/空=不变）', () => {
    expect(ModelServiceUpdateSchema.safeParse({}).success).toBe(true)
    expect(ModelServiceUpdateSchema.safeParse({ provider: null }).success).toBe(true)
    expect(ModelServiceUpdateSchema.safeParse({ provider: '自定义' }).success).toBe(true)
    expect(ModelServiceUpdateSchema.safeParse({ provider: 7 }).success).toBe(false)
  })
})
