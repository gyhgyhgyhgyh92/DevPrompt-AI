# Tasks

> 权威详设：`doc-阶段/2026-10-10-阶段五-W3三套差异化与加权推荐-实施计划.md` §3（每任务先读对应小节再执行）。
> 通用规约：TDD 先红后绿；每任务收口跑全量门禁（ruff check/format / mypy / pytest / scripts/check_architecture.py）全绿才算完成；子代理零 git 操作，主流程串行提交。

- [x] Task 1: 5A 文档修复与实测基座（T5-11①）
  - [x] 1.1 功能清单 F-804 拆分为两条可执行验收（方案内容 diff 对照 + 评分/推荐标记一致性；LLM 非确定性不要求零差异）+ 变更记录
  - [x] 1.2 新建 `scripts/measure_ranking.py`（复用 measure_recall.py 框架：build_candidates ≤25 → rank_components → top1==expected 判定；JSON 报告含 `metric_source:"LLM 排序准确率"`；--dry mock 模式）
  - [x] 1.3 `--dry` 对 1 仓跑通 exit 0
- [x] Task 2: 5B ranking 纯函数域层（T5-4/T5-5/T5-6）
  - [x] 2.1 `domain/ranking/ports.py`：VariantFeatures + PreferenceStore Protocol + AdoptionRecord
  - [x] 2.2 `preference.py`：FEATURE_TABLE（实现前重读 F-402 逐值核对——**执行期裁决 D-5B-1：原文为分维不同值，非计划初稿单行值；已按原文实现**）
  - [x] 2.3 `score.py`：weighted_total + validate_weights（≠1.0→9002）+ 手工验算固定断言
  - [x] 2.4 `recommend.py`：MUST-27 五条优先级命中即止 + 四情形 + 压序 + reason 文案测试（**边界裁决：d==0.12 按 MUST-27 条件③严格不等号归条件⑤「标+分差较小」，宪法优于任务清单初稿**）
  - [x] 2.5 单测 ≥25 用例全绿（实际 44）+ 架构检查（ranking 禁 import 基础设施）
- [x] Task 3: 5C 三套生成扩展（T5-1/T5-2）
  - [x] 3.1 `generate/ports.py` 加 generate_variants + MultiVariantDraft（n∈[1,3] 校验）
  - [x] 3.2 `harness/llm.py` LLMGenerator.generate_variants（单次调用 + A/B/C 模板约束：A 禁行号/C 含行号+token 出处+测试指令；档位裁剪）
  - [x] 3.3 契约测试（Fake LLM）：套数/level 单调/字段/禁行号
  - [x] 3.4 DeepSeek 真实冒烟一条：三套梯度人工抽检
- [x] Task 4: 5D L3 偏好记忆（T5-7/T5-8）
  - [x] 4.1 schema.py 追加 preference_vectors + adoption_history DDL（IF NOT EXISTS）
  - [x] 4.2 `memory/preference_store.py` SQLitePreferenceStore（to_thread，user_id 分区间）
  - [x] 4.3 更新规则五类单测（采纳/编辑采纳/跳过趋向中性/衰减 0.9/裁剪）——**先读 F-503 原文，矛盾即停（D-5D-1）**
  - [x] 4.4 service.feedback 接入（编辑距离 difflib）+ get_preference 接 L3
- [x] Task 5: 5E Jev 决策层（T5-9）
  - [x] 5.1 核实 typesafe-sdk 0.7.2 API（不符即停 D-5E-1）
  - [x] 5.2 `decision/jev.py` 三方法 + JEV_MODEL_ID 断言 + 30000 截断 state.truncated + 429 指数退避
  - [x] 5.3 create_decider 双路径（key→Jev / 无 key 或连续失败→LLM，记 decider.switched）
  - [x] 5.4 契约一致性测试（Jev mock vs fallback 输出逐字段一致）
- [x] Task 6: 5F 服务编排与契约升级（**BREAKING**）
  - [x] 6.1 FlowSnapshot variant→variants + ranking: RankingView（schemas.py 同步）
  - [x] 6.2 _generate_and_finish 重写（GENERATING→RANKING→DONE；score_prompts→归一化→加权→decide_mark→事件；仅 A 档跳过打分不计算 d）
  - [x] 6.3 RETRIEVING 接 rank_components（MUST-14 缓存键：路径+sha256+阈值 hash，TTL 30min）
  - [x] 6.4 routes/schemas 同步（GET /preference 接 L3；feedback 补 variant/edited_text；PUT preference 与 /history 维持 501）
  - [x] 6.5 全量门禁 + API 测试更新 + uvicorn 冒烟（三套+标记；escape 单套 A 无 ranking）
- [x] Task 7: 5H 排序准确率实测与出口验收（T5-10）—— **生死线 58%＜80% 未达标，MUST-25 上报后用户裁决「方案甲」（LLM 决策转正），依决策树授权继续**
  - [x] 7.1 measure_ranking 全量 100 条（LLM 版，指标标注）—— 58/100=58.0%，metric_source=LLM 排序准确率
  - [x] 7.2 主流程复跑判定：≥80% 通过 / <80% **停止上报甲乙**（MUST-25）—— 402 污染排除，最好上限 68% 仍不达标，已上报；用户裁决方案甲
  - [x] 7.3 出口验收：三套+推荐标记、双路径、失败归因报告 eval/recall/report-ranking-2026-10-11.md（三套/标记/双路径由 257 测试 + uvicorn 冒烟覆盖；归因报告落档）
  - [x] 7.4 真源 §1/§13 收口 + F-202 补全确认（T5-11②）—— 真源 §1 阶段五 ✅ + §13 甲裁决记录；F-202 三处空规格补全

# Task Dependencies

- Task 1 ∥ Task 2（W1 可并行）
- Task 3 ∥ Task 4 ∥ Task 5（W2 可并行；均依赖 Task 2 的 ports 契约）
- Task 6 依赖 Task 2+3+4+5 全部合流（W3）
- Task 7 依赖 Task 1（脚本）+ Task 6（编排）（W4）
- 任何任务触发 spec 不确定项（D-5D-1/D-5E-1/生死线）→ 暂停上报用户，不得擅自决定
