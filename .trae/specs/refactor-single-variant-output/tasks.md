# Tasks

- [x] Task 1: 收敛领域模型，移除档位概念
  - [x] SubTask 1.1: `domain/generate/ports.py` 删除 `Level`、`VALID_LEVEL_SETS`、`MultiVariantDraft`；`VariantDraft` 去掉 `level`，新增 `fallback: bool = False`；`GenerationContext` 去掉 `level`
  - [x] SubTask 1.2: `GeneratePort` 只保留 `generate_single` 与 `answer`，删除 `generate_variants` 声明
  - [x] SubTask 1.3: 删除 `domain/generate/variants.py`
  - [x] SubTask 1.4: 全库清理上述符号的 import 与调用（grep 复核无命中）

- [x] Task 2: 生成层收敛为单套，B 成为唯一出口
  - [x] SubTask 2.1: `harness/llm.py` 删除 `generate_variants`、`_build_multi_system`、`_build_multi_user`；`generate_single` 成为唯一生成入口
  - [x] SubTask 2.2: 单套 user 构造保留 `target_excerpt`、`design_tokens`、`previous_variants`、`history_block`、`memory_block`
  - [x] SubTask 2.3: 删除 `templates/c_thorough.py`；路由收敛为「B 常规 / A 兜底 / reply」
  - [x] SubTask 2.4: `b_standard.py` 吸收 C 的硬性要求（锚点须来自片段、必须给原→新代码）
  - [x] SubTask 2.5: `grep -rn "template\.c\.\|template\.multi\." src` 无命中

- [x] Task 3: 修正断言覆盖率账本
  - [x] SubTask 3.1: `match_claims(..., evidence_text="")` 新形参
  - [x] SubTask 3.2: `symbol` / `line` / `file` 优先在 `evidence_text` 核对，保留事实证据回退
  - [x] SubTask 3.3: `token` 优先在 `design_tokens` 证据核对
  - [x] SubTask 3.4: `Claim.negates` 增加 `"test"` → `test_file_exists`
  - [x] SubTask 3.5: `_audit_claims` 组装并透传 `evidence_text`

- [x] Task 4: 统一核验并入 B 输出链路
  - [x] SubTask 4.1: `_verify_c_anchors` → `_verify_anchors`，去掉 C 档门控
  - [x] SubTask 4.2: 顺序固定「写方案 → 断言对账 → 锚点核验 → 交付门 → 交付」
  - [x] SubTask 4.3: 判不清的锚点不降级

- [x] Task 5: 状态机与动作集收敛
  - [x] SubTask 5.1: `AgentAction` 删除 `RANK`
  - [x] SubTask 5.2: `FlowState` 删除 `RANKING` 及相关转移边
  - [x] SubTask 5.3: 调度规则删除 rank 与「套数 ≥2」表述
  - [x] SubTask 5.4: `run_agent_loop` 移除 RANK 分派

- [x] Task 6: 交付门收敛
  - [x] SubTask 6.1: `DeliveryInput` 删除 5 个推荐字段
  - [x] SubTask 6.2: `DeliveryVerdict` 删除 `can_mark_c` / `can_mark_recommend`
  - [x] SubTask 6.3: 删除 4 条档位/推荐文案（zh + en）
  - [x] SubTask 6.4: 移除 `variant_count` / `expected_variant_count` 判定

- [x] Task 7: 服务编排与接口契约
  - [x] SubTask 7.1: `_act_generate` 单套 + A 兜底一次（`fallback=True`）
  - [x] SubTask 7.2: 删除 `_act_rank` / `_should_offer_three` / `_preferred_level`；保留 `_rank_top`
  - [x] SubTask 7.3: `FlowSnapshot.variant` 单对象；删除 `ranking` / `ranking_skip_reason`
  - [x] SubTask 7.4: `FlowSnapshotResponse.variant`；删除 `RankingViewPayload`
  - [x] SubTask 7.5: 删除 `domain/ranking/` 与相关 import

- [x] Task 8: 前端契约同步（BREAKING）
  - [x] SubTask 8.1: 删除 `ConfidenceNotice`；`AssistantBlock` 渲染单卡片
  - [x] SubTask 8.2: 删除 `VariantTabs`、`RecommendBadge`、`ScoreDetail`
  - [x] SubTask 8.3: store / OptimizePage / api / schemas 同步 `variant` 单对象
  - [x] SubTask 8.4: i18n 清理 `ranking.*`、档位与页签键；新增 `optimize.fallback_notice`

- [x] Task 9: 测试与全量验证
  - [x] SubTask 9.1: 后端测试更新（删除 variants/ranking 专属用例，新增单套/兜底/账本五类用例）
  - [x] SubTask 9.2: 前端测试更新（42 文件 / 314 用例通过）
  - [x] SubTask 9.3: ruff / format / mypy / pytest 全绿（1301 passed, 11 skipped）
  - [x] SubTask 9.4: 架构检查通过；召回率 95/100 = 95%
  - [x] SubTask 9.5: E2E 三轮复测完成（单套产出、`variant` 字段、覆盖率 21%/26%/35% → ≥80%/79%/67%）

# Task Dependencies

- Task 2 依赖 Task 1
- Task 3 依赖 Task 1
- Task 4 依赖 Task 3
- Task 5 依赖 Task 1
- Task 6 依赖 Task 1
- Task 7 依赖 Task 2、Task 4、Task 5、Task 6
- Task 8 依赖 Task 7
- Task 9 依赖 Task 1~8
