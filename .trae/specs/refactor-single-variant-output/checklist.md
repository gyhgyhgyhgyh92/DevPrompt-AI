# Checklist

## 唯一输出路径

- [x] 代码库中不存在 `generate_variants` 的调用（`grep -rn "generate_variants" src` 无命中）
- [x] 正常轮次的快照只含一个 `variant` 对象，且 `title` / `body` 非空
- [x] `FlowSnapshotResponse` 中已无 `variants`、`ranking`、`ranking_skip_reason` 字段
- [x] 方案正文由 B 模板生成（`templates/b_standard.py` 的 SYSTEM 出现在生成提示词中）

## 兜底降级

- [x] 主流程正常时，A 模板不被调用（E2E 三轮 `fallback` 均为 false）
- [x] 注入一次生成异常后，系统用 A 模板产出兜底方案，且 `variant.fallback == true`（单测覆盖）
- [x] 兜底也失败时返回明确失败结果，不产生伪造正文
- [x] 兜底披露文案出现在 `message`（`optimize.fallback_notice`）

## 核验并入 B

- [x] `_verify_c_anchors` 已重命名为 `_verify_anchors`，无 `level == "C"` 判断
- [x] 单套方案也会执行锚点核验：无效锚点计入交付门并披露
- [x] 读取失败（判不清）的锚点不触发降级
- [x] 断言对账在交付前执行，`claims_undeclared` 仍能触发 RED

## 覆盖率账本

- [x] 引用 JSX 组件的 `symbol` 断言，在片段含该组件时计为覆盖（单测覆盖）
- [x] 引用非目标文件的 `file` 断言，在令牌证据含该路径时计为覆盖（单测覆盖）
- [x] `line` 断言 `path:233` 在片段含 `233|` 时计为覆盖（单测覆盖）
- [x] `token` 断言 `colorError` 在令牌证据命中时计为覆盖（单测覆盖）
- [x] `absence negates=test` 在 `test_file_exists` 为假时计为覆盖（单测覆盖）
- [x] 以「新增图书按钮改红色」原句复测：覆盖率由 35% 提升至 ≥80%（R1 交付门 GREEN，无覆盖率披露）；R2 79%、R3 67%，均显著高于改造前的 21% / 26% / 35%

## 档位与推荐移除

- [x] `grep -rn "VALID_LEVEL_SETS\|MultiVariantDraft\|resolve_level\|expand_levels\|plan_levels" src` 无命中
- [x] `VariantDraft` 与 `GenerationContext` 均无 `level` 字段
- [x] `AgentAction` 无 `RANK`；`FlowState` 无 `RANKING`
- [x] `domain/ranking/` 目录已删除；`decide_mark` / `normalize_fit` / `weighted_total` 无引用
- [x] `DeliveryVerdict` 无 `can_mark_c` / `can_mark_recommend`
- [x] 前端无 `ConfidenceNotice`、无推荐徽标；方案区渲染单卡片

## 不可误删项（反向校验）

- [x] `service._rank_top` 仍存在且被调用（候选符号排序）
- [x] `domain/retrieval/candidates.py` 的 `build_candidates` / `reorder_by_lexicon` 未被改动
- [x] `templates/a_conservative.py` 仍存在（兜底专用）
- [x] `domain/generate/anchors.py` 与 `claims.py` 仍在且被调用

## 门禁

- [x] `uv run ruff check .` 通过
- [x] `uv run ruff format --check .` 通过（297 文件）
- [x] `uv run mypy src` 通过（163 文件）
- [x] `uv run pytest tests -q` 全绿（1301 passed, 11 skipped）
- [x] `uv run python scripts/check_architecture.py` 通过
- [x] `uv run python scripts/measure_recall.py` 召回率 95/100 = 95%（≥80%）
- [x] 前端 `npm run lint` / `vitest run`（42 文件 314 用例）/ `npm run build` 全绿

## 端到端

- [x] `eval/multiturn/run_3rounds.py` 三轮均为单套输出
- [x] 三轮 `fallback` 均为 false（未误触发兜底）
- [x] 三轮的 `variant.body` 均含四段式小标题
- [x] 三轮的断言覆盖率均明显高于改造前的 21% / 26% / 35%

## 备注（非阻塞）

- R3 的 A2 判据（`PageContainer` + `extra`）未命中：该轮目标是表格行内的「编辑」按钮，不在 `extra` 内，属判据口径偏严而非实现缺陷；A1/A3/A4/A5 均通过。
- `memory/project_note_store.py` 与 `domain/context/build_context.py` 保留读取旧 `ranking` 字段的兼容分支，用于历史数据回放。
