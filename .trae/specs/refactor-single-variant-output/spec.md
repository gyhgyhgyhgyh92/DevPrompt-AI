# 单套方案输出重构 Spec

## Why

当前系统每轮同时产出 1~3 套方案（A 保守 / B 标准 / C 激进），再由落分排序选一套推荐。实测暴露出三个结构性问题：

1. **C 档永远不可达**：`token_defined` 只搜 CSS 自定义属性 `--xxx`，AntD 类项目恒为假，`is_evidence_complete` 永远 False，`resolve_level` 最高只到 B —— C 模板与其核验逻辑长期空转。
2. **A 档稀释质量**：A 档被要求「信息不足时仍输出」，在多轮中经常被选为推荐，正文退化为「待定位」；其断言留白还会拉低跨档累加的覆盖率。
3. **推荐判定是噪声源**：单套时仍走 rank，产出「分差较小」这类无意义结论；推荐又被坏账本误撤销，形成假阴性。

用户的决策：**只输出一套**，保留 B（标准版）作为唯一出口，A 仅在异常时兜底，C 的核验能力并入 B。同时把上一轮排查出的覆盖率账本缺陷一并修复。

## What Changes

- **B 成为唯一对外输出模块**：所有方案由 `templates/b_standard.py` 生成，普通轮次恒产出 1 套。
- **A 降级为兜底通道**：仅在主流程抛错或产出无效（空正文/结构不合法）时启用；**禁止**进入常规路径。
- **C 的核验逻辑并入 B**：`anchors.extract_anchors/verify_anchors` + `_probe_anchor` 改为每套方案的常规交付前校验；`c_thorough.py` 删除。
- **BREAKING** 移除档位概念：`Level`、`VALID_LEVEL_SETS`、`resolve_level`、`expand_levels`、`plan_levels`、`VariantDraft.level`、`GenerationContext.level`、`MultiVariantDraft` 全部删除。
- **BREAKING** 移除方案打分与推荐层：`domain/ranking/*`、`_act_rank`、`AgentAction.RANK`、`FlowState.RANKING`、`decide_mark`、前端 `ConfidenceNotice`。
- **BREAKING** 接口契约：`FlowSnapshotResponse.variants: list` → `variant: VariantPayload | None`；`ranking`、`ranking_skip_reason` 删除。
- **修复断言覆盖率账本** 5 类根因（symbol/line/file 证据源、token 证据源、absence 映射）。
- 交付门收敛：删除 `can_mark_c`、`can_mark_recommend`、`variant_short`、`single_variant`、`recommend_revoked` 判定，保留 facts / coverage / anchor / attribution。

## Impact

- 受影响能力：方案生成、交付门禁、agentic 调度、会话快照契约、前端结果渲染、断言账本
- 受影响代码（后端）：`domain/generate/{ports,anchors,claims,variants}.py`、`domain/generate/templates/*`、`domain/delivery/gate.py`、`domain/agent/{action,ports}.py`、`domain/ranking/*`（删除）、`harness/llm.py`、`service.py`、`interfaces/api/schemas.py`、`state.py`、`common/i18n.py`
- 受影响代码（前端）：`pages/OptimizePage.tsx`、`components/optimize/{VariantTabs,ConfidenceNotice,AssistantBlock}.tsx`（后两者删除或重写）、`stores/useOptimizeStore.ts`、`api/{endpoints,stream}.ts`、`i18n/locales/*.json`
- 受影响测试：`tests/domain/generate/*`、`tests/test_agent_loop.py`、`tests/test_delivery_gate*.py`、`tests/harness/test_llm*.py`、`frontend/src/**/*.test.ts(x)`

---

## ADDED Requirements

### Requirement: 唯一输出路径

系统 SHALL 在每个正常轮次只产出一套方案，且该方案 MUST 由 B（标准版）模板生成。系统中不得存在第二条常规方案产出路径。

#### Scenario: 常规轮次单套输出
- **WHEN** 一轮优化正常完成（未抛错，产出正文非空）
- **THEN** 快照中 `variant` 为单个对象且非空
- **AND** `variants` 字段不再存在
- **AND** 本轮未触发兜底标记

#### Scenario: 单套时不再打分
- **WHEN** 本轮只产出一套方案
- **THEN** 不执行任何方案间比较
- **AND** 快照中不存在 `ranking` / `ranking_skip_reason`

### Requirement: 兜底降级仅在异常时触发

系统 SHALL 仅在主流程抛错或产出无效时启用 A（保守版）模板重新生成；A MUST NOT 出现在常规路径。

#### Scenario: 主流程异常触发兜底
- **WHEN** B 模板生成抛 `GenerationError` 或返回结构非法
- **THEN** 系统使用 A 模板重试一次
- **AND** 快照标记 `fallback=true`，并在 `message`/交付门披露中说明「已降级为保守输出」

#### Scenario: 兜底仍失败
- **WHEN** A 兜底同样失败
- **THEN** 返回明确的失败快照（`status=aborted` 或错误响应），不得伪造方案正文

### Requirement: 统一核验并入 B

系统 SHALL 在交付前对每套方案执行两项核验，且核验逻辑 MUST 位于 B 的输出链路中，不得依赖任何档位判断。

#### Scenario: 锚点核验
- **WHEN** 方案正文包含 `path:line` 锚点
- **THEN** 逐条核验文件存在性与行号是否越界
- **AND** 明确无效的锚点计入交付门并披露；判不清（读取失败）不降级

#### Scenario: 断言对账
- **WHEN** 方案声明了 `claims`
- **THEN** 逐条与取证证据核对，覆盖率低于阈值时降级披露
- **AND** 未声明 claims 时按 `undeclared` 处理，不得记为 100%

### Requirement: 断言覆盖率账本修正

系统 SHALL 用「目标代码片段 + 设计令牌证据 + 目标文件存在性」作为断言核对的证据源，覆盖组件引用、跨文件引用、行号与令牌四类断言。

#### Scenario: 引用第三方组件
- **WHEN** 方案声明 `kind=symbol target=Button`，且 `Button` 出现在目标代码片段中
- **THEN** 该断言计为已覆盖

#### Scenario: 引用其他文件
- **WHEN** 方案声明 `kind=file target=src/styles/antdTheme.ts`，且该路径出现在令牌证据或片段中
- **THEN** 该断言计为已覆盖

#### Scenario: 行号断言
- **WHEN** 方案声明 `kind=line target=path/to/X.tsx:233`，且片段中出现 `233|`
- **THEN** 该断言计为已覆盖

#### Scenario: 令牌断言
- **WHEN** 方案声明 `kind=token target=colorError`，且设计令牌证据包含 `colorError`
- **THEN** 该断言计为已覆盖

#### Scenario: 如实的否定断言
- **WHEN** 方案声明 `kind=absence negates=test`「未找到测试文件」，且 `test_file_exists` 为假
- **THEN** 该断言计为已覆盖

### Requirement: 单对象对外契约

`FlowSnapshotResponse` SHALL 以单个 `variant` 字段承载方案。

#### Scenario: 正常响应
- **WHEN** 客户端读取快照
- **THEN** 字段为 `variant: { title, body, changes, claims, fallback }`
- **AND** 不存在 `variants` / `ranking` / `ranking_skip_reason`

---

## MODIFIED Requirements

### Requirement: 交付证据门

交付门 SHALL 仅基于事实通过率、断言覆盖率、锚点有效性、改动归属判定三态（GREEN/YELLOW/RED），不再包含任何档位或推荐语义。

判定项调整：
- 删除 `can_mark_c`、`can_mark_recommend`
- 删除 `variant_short`（本次仅 N 套）、`single_variant`（单套披露）、`recommend_revoked`、`no_recommend`
- 保留 `no_target`、`facts_failed`、`claims_undeclared`、`anchor_invalid`、`coverage`、`impact_uncovered`

### Requirement: Agentic 调度动作集

动作集 SHALL 移除 `RANK`；`DELIVER` 的准入条件由「方案已生成且可收尾」取代「已生成且套数 ≥2」。

### Requirement: 生成提示词

多套提示词的「档位一致性 / 长度梯度 / 逐套 claims」规则 SHALL 替换为单套规则：四段式结构（定位/实施/一致性检查/输出要求）、逐条 claims、禁止编造锚点。

---

## REMOVED Requirements

### Requirement: 档位体系（A/B/C 与 MUST-28 前缀集）

**Reason**: 只输出一套后，档位不再承载任何区分语义；C 档在当前事实模型下不可达。
**Migration**: 直接删除 `Level`、`VALID_LEVEL_SETS`、`resolve_level`、`expand_levels`、`plan_levels`、`level` 字段与相关 i18n 键；旧数据中 `level` 字段读取时忽略。

### Requirement: 方案打分与推荐

**Reason**: 单套方案无可比对象；推荐还会被覆盖率误判反向污染。
**Migration**: 删除 `domain/ranking/*`、`_act_rank`、`decide_mark`、`AgentAction.RANK`、`FlowState.RANKING`、前端推荐徽标；置信度改由交付门与待确认项表达。

### Requirement: 多套同次生成

**Reason**: 一次只产出一套。
**Migration**: 删除 `generate_variants`、`MultiVariantDraft`、`_build_multi_system/user`；`generate_single` 成为唯一生成入口。

---

## 重要边界说明（执行者必读）

| 名称 | 处置 | 原因 |
|---|---|---|
| `service._rank_top` | **保留** | 它排序的是**候选符号**，属检索链路，与方案推荐无关 |
| `domain/retrieval/candidates.py` 的打分 | **保留** | 同上 |
| `templates/a_conservative.py` | **保留** | 作为唯一的降级兜底模板 |
| `templates/c_thorough.py` | **删除** | 核验逻辑迁入 B，模板本身不再需要 |
| `domain/ranking/score.py` | **删除** | 仅被 `_act_rank` 使用（`normalize_fit` / `weighted_total`） |
