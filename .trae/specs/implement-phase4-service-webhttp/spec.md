# 阶段四（W2 服务层与 Web HTTP）实施 Spec

> **执行蓝图**：`doc-阶段/2026-10-06-阶段四-W2服务层与WebHTTP-实施计划.md`（v1.1，SQLite 版）——本 spec 是其规格化封装，任务步骤/完整代码以该计划为准，spec/tasks 只维护契约、顺序与验收。

## Why

阶段三检索层已通过生死线（召回率 95%），阶段四开工许可已解锁。需交付唯一业务入口 `ForgeService`、优化流程状态机（SQLite L1 持久化）、自适应反问（MUST-26 v1.1）、单套生成与 Web HTTP 层（`/api/v1` 九端点），达成 W2 出口门禁「Web HTTP 可完成单套提示词生成，含反问机制」。

## What Changes

- 4A 配置基线：`max_followup_rounds` → `followup_soft_round_guard`/`followup_cost_budget`；新增 `db_path`；**移除 aiomysql/PyMySQL 依赖**（存储回改 SQLite 定稿）——**BREAKING**（配置语义变更，零消费者）
- 4B 状态机与 L1：`domain/models.py` 追加 `FlowSession`/`SessionStore`；`state.py`（FlowState 9 态 + CAS 乐观锁 6001 + load_or_create 6003）；`memory/schema.py`（SQLite DDL）；`memory/session_store.py`（`SQLiteSessionStore`，标准库 sqlite3 + `asyncio.to_thread` + WAL）
- 4D 探针与反问编排：`domain/decision/{probes,followup}.py`（`UnknownItem`/`build_unknowns`/`GuardrailState`，纯逻辑零 I/O）
- 4E 单套生成：`domain/generate/{ports,variants}.py` + `templates/{a,b,c}.py` + `harness/llm.py` 追加 `LLMGenerator`/`last_usage`（F-805 起建）+ `harness/guardrails.py` 追加 `validate_variant`
- 4G L2 与横跨：`memory/project_notes.py`（Git notes）+ `scripts/smoke_provider.py`（F-802 四项冒烟）
- 4C 服务入口：`service.py`（`ForgeService` 六方法 + `build_default` + `FlowSnapshot`）
- 4F Web HTTP：`interfaces/api/`（FastAPI 薄壳 + `/api/v1` 九端点 + followup 三模式 answers/escape/guardrail_action）
- 4H 出口验收：`resume` 恢复入口、端到端实测、真源更新

## Impact

- Affected specs: 真源 §5 阶段四（T4-1~T4-10）、F-001/002/203/204v1.1/205/301单套/501/502/601/602/802/805
- Affected code: `src/devprompt_ai/{config,service,state,main}.py`、`domain/{models,decision/*,generate/*}`、`harness/{llm,guardrails}.py`、`memory/{schema,session_store,project_notes}.py`、`interfaces/api/*`、`scripts/smoke_provider.py`、`pyproject.toml`+`uv.lock`、`.env.example`
- Affected docs（收口时）：真源 §1/§13、本 spec checklist

## 硬约束（用户指令 + 宪法）

1. **边界锁定**：严格限于计划 4A~4H；越界需求 → 暂停并标记「待讨论项」上报，严禁擅自扩展（如提前做 RANKING/Web/L3 落库）
2. **宪法优先**：执行细节与宪法冲突时以宪法为准并记录冲突原因（计划 v1.1 已按宪法 v1.1 对齐，含 4A 的 BREAKING 标注）
3. **门禁推进**：每子阶段 DoD（计划各节 1.4/2.4/…验收表）通过并显式报告后才进下一子阶段；失败即停，禁止「让它过去」（SHOULD-03）
4. **质量闭环**：TDD 先红后绿；每子阶段收口跑九命令门禁；缺陷与偏差记录进 9.5 执行留痕区
5. **git 约定**：沿用阶段三模式——**子代理零 git 操作**，主流程每子阶段收口串行提交（MUST-21，4A 提交含 `BREAKING CHANGE:`）

## ADDED Requirements

### Requirement: 优化流程状态机与 L1 持久化（F-002/F-501）
状态机 SHALL 为 `state.py` 唯一实现（MUST-07）：9 态转移表（含 RETRIEVING→ASKING 的 manual_required 直达、GENERATING→RANKING 阶段五预留）；转移经 `SessionStore` CAS 持久化，版本冲突抛 `StateError(6001)`、非法转移不落盘、流程不存在抛 6003。存储 SHALL 为 `SQLiteSessionStore`（WAL + busy_timeout 5000 + 幂等建表，SQL 仅限 `memory/`）。

#### Scenario: 中断恢复
- **WHEN** 流程在 ASKING 状态中断后以同 session_id 恢复
- **THEN** 状态与 data（candidates/facts/unknowns/clarifications）完整还原

#### Scenario: 并发写冲突
- **WHEN** 两个写入者以同一 version 保存
- **THEN** 后到者 `save` 返回 False，调用方抛 6001，状态不错乱

### Requirement: 自适应反问（F-204 v1.1 / MUST-26）
反问 SHALL 由 `unknowns[]`（具体未决事实）驱动：非空 → 批量提问（每问绑定键/原因/推断/问法）；空 → 零提问直接生成；用户任一轮可逃生「直接生成」（`followup.escaped`）；护栏（轮数 ≥`followup_soft_round_guard` 或 token 超 `followup_cost_budget`）触发 `followup.guardrail` 显式裁决而非静默终止，裁决「继续」后清零。**禁止**泛化提问；LLM 不自评信息充分性。

#### Scenario: 护栏显式裁决
- **WHEN** 单流程追问轮数达到软护栏阈值且 unknowns 仍非空
- **THEN** 返回 `status="guardrail"`（停 CONFIRMING），用户裁决「继续」后 rounds 清零回到 ASKING，轮数无上限

### Requirement: 单套生成与档位（F-301 单套/F-205/MUST-28）
生成 SHALL 经 `GeneratePort.generate_single(ctx)` 按信息完备度档位（A/B/C）路由三套模板之一；`resolve_level`：取证完成→C、有符号→B、否则 A；逃生/护栏裁决直接生成时强制 A 档保守版。输出经 `validate_variant`（标题/正文非空）。

#### Scenario: 零提问直达
- **WHEN** 七项取证全过且探针置信度 ≥0.75
- **THEN** optimize 一次调用直达 `status="done"`（C 档），不产生任何反问

### Requirement: Web HTTP 入口（F-601/F-602/MUST-10）
Web HTTP 层 SHALL 提供 `/api/v1` 九端点（health / optimize / progress SSE / followup 三模式 / result / feedback / preference / project·scan / history）；业务全部经 `ForgeService`，路由层零业务判定；错误信封仅 code+message+request_id、不回传密钥（MUST-19）；501 占位端点如实标注（D-4F-1/D-4F-2）。

#### Scenario: 反问交互闭环
- **WHEN** optimize 进入 ask 状态
- **THEN** 响应携带问题列表（键/推断/原因），经 followup `answers` 批量答复后推进；`escape` 任一轮逃生；`guardrail_action` continue/generate 两选项生效

## MODIFIED Requirements

### Requirement: 配置基线（F-003）
`config.py` SHALL 删除 `max_followup_rounds` 与（若预置的）`mysql_*` 六键，新增 `followup_soft_round_guard=10`、`followup_cost_budget=0.0`（口径=单流程 LLM token 总数）、`db_path="~/.devprompt-ai/devprompt.db"`；pyproject SHALL 移除 aiomysql/PyMySQL 并保持 `uv lock --check`/`--frozen` 通过。**BREAKING CHANGE** 标注于 4A 提交。

## 验收基线（W2 出口门禁 = 4H DoD）

- 端到端：`POST /api/v1/optimize` 真库走通（含 followup answers/escape/guardrail_action 各≥1 次演示、result 端点中断恢复）
- 质量门禁：九命令全绿（ruff check/format、format --check、mypy、pytest、架构检查、前端四脚本）
- 真源同步：§1 阶段四 ✅ + §13 变更记录 + 计划 9.5 留痕区
