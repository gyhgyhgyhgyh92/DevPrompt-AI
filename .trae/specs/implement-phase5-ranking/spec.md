# Phase 5 Ranking & Recommendation Spec

## Why

实现阶段五（W3）：三套差异化方案生成 + 四阶段加权推荐 + L3 偏好记忆，并用真实语料实测**排序准确率 ≥80%（生死线第二段，MUST-25）**。权威实施计划：`doc-阶段/2026-10-10-阶段五-W3三套差异化与加权推荐-实施计划.md`（子阶段详设/步骤/代码骨架以该文档为准，本 spec 是其可执行约束摘要）。

## What Changes

- 新增 `domain/ranking/` 四模块：ports（PreferenceStore Protocol）/preference（FEATURE_TABLE+match_score）/score（加权 0.6/0.4）/recommend（MUST-27 五条优先级）
- 新增 `generate_variants`（单次 LLM 调用产出 A/B/C 三套，档位裁剪联动 resolve_level）
- 新增 L3 偏好记忆：preference_vectors + adoption_history 双表 + SQLitePreferenceStore + feedback 接入
- 新增 `decision/jev.py`（JevDecider 三方法 mock 实现）+ create_decider 双路径切换（decider.switched）
- service RANKING 态真实接线 + RETRIEVING 段接入 rank_components（MUST-09 顺序 + MUST-14 缓存键）
- **BREAKING**：FlowSnapshot `variant` → `variants: list[VariantDraft]` + 新增 `ranking: RankingView | None`；HTTP 契约同步（GET /preference 接 L3 真实向量；PUT /preference 与 /history 维持 501/9004）
- 文档修复：F-804 拆分可执行定义（T5-11①）、F-202 补全随 5E 落地（T5-11②）
- 实测：scripts/measure_ranking.py + 100 条语料排序准确率判定

## Impact

- Affected specs: F-301~F-304（三套生成）、F-401~F-404（打分/偏好/加权/推荐）、F-503/F-603（L3/采纳）、F-202（Jev）、F-801 第二段、F-804
- Affected code: domain/ranking/*、domain/generate/ports.py、harness/llm.py、decision/jev.py、decision/fallback.py、memory/{schema,preference_store}.py、service.py、interfaces/api/{schemas,routes}.py、scripts/measure_ranking.py
- 宪法约束：MUST-08（判定位置）、MUST-09（检索先于排序）、MUST-12（可降级+双路径同构）、MUST-14（缓存键）、MUST-25（生死线）、MUST-27/28（诚实策略/不越级）

## ADDED Requirements

### Requirement: 三套差异化生成（T5-1/T5-2）
系统 SHALL 在同一次 LLM 调用中产出最多三套方案（A/B/C），同一事实三套描述一致；仅 A 档可输出时为单套（MUST-28 附注）。
- **WHEN** 信息完备度支持 3 档 **THEN** variants 长度=3，level 呈 A<B<C，C 含行号+token 出处+测试指令，A 无行号
- **WHEN** 仅 A 档 **THEN** variants 长度=1 且跳过打分与推荐（不计算 d）

### Requirement: 四阶段加权推荐（T5-3~T5-6）
- 适配度=score/4（五档 0-4，三问共享 state）；匹配度=1−mean(|偏好ᵢ−方案特征ᵢ|)（特征表 0.25/0.58/1.0）；总分=0.6×适配度+0.4×匹配度（权重和≠1.0 报 9002）
- 推荐标记按 MUST-27 五条**优先级命中即止**：①top conf<0.6 ②任一档 conf<0.4 ③d<0.12 → 不标（各给具体原因）④d≥0.5 → 标 ⑤0.12≤d<0.5 → 标+「分差较小」
- **WHEN** 四种情形构造用例 **THEN** 判定与 reason 文案逐一正确

### Requirement: L3 偏好记忆（T5-7/T5-8）
采纳/编辑采纳/跳过三类隐式信号按 F-503 规则更新偏好向量（滑动平均衰减 0.9，裁剪 [0,1]，跳过趋向中性——开放决策 #1 已定稿）；采纳历史入库。
- **WHEN** 连续采纳 C **THEN** detail_level 向 C 特征方向移动
- **WHEN** 跳过 **THEN** 各维度向 0.5 回归

### Requirement: Jev 决策层与双路径同构（T5-9）
JevDecider 实现三方法；JEV_MODEL_ID 钉死 jev-1.13.0；state 30000 token 硬限截断记 state.truncated；429 指数退避；无 key 自动切 LLM 版记 decider.switched；两实现输出结构逐字段一致。
- **WHEN** 无 TYPESAFE_API_KEY **THEN** 全链路可跑（SHOULD-11），测试用 mock 完成

### Requirement: 排序准确率实测（T5-10，生死线）
100 条签收语料全量实测正确目标排第一；报告标注「LLM 排序准确率」（Jev 未获批不得混用）；**≥80% 通过，<80% 停止并上报用户甲/乙裁决**。

## MODIFIED Requirements

### Requirement: FlowSnapshot 契约 v2 **BREAKING**
`variant: VariantDraft|None` 移除，改为 `variants: list[VariantDraft]` + `ranking: RankingView|None`（fit/pref/total/confidence/gap/marked/reason/variant）。HTTP 测试与响应同步。迁移：单套场景=variants 长度 1 + ranking=None。

### Requirement: service RANKING 编排
GENERATING→RANKING→DONE 真实流转；score_prompts 三问共享 context；`candidates[0]` 升级为 rank_components top1（缓存键=项目路径+原句 sha256+阈值配置 hash，TTL 30 分钟）。

## REMOVED Requirements

无（无功能项移除；契约字段变更为 MODIFIED）。

## 不确定项上报（MUST-05，触发即停）

| # | 事项 |
|---|---|
| D-5D-1 | F-503 三个数值（+1.0/0.9/0.3）合成张力——实现前重读功能清单原文，矛盾即停上报 |
| D-5E-1 | typesafe-sdk 0.7.2 真实 API 未实测——核实不符即停 |
| D-5F-1 | fallback.py rank/score 实现状态——5F 前读源核实，缺失则补实现（属 T5-9） |
| 生死线 | <80% → 停，甲/乙二选一由用户裁决（MUST-25） |
