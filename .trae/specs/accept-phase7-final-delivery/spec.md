# 阶段七 · 整体验收与交付 Spec

> 权威依据：`DevPrompt-AI-实施真源文档.md` §8（阶段七 T7-1~T7-7）与 §8.4 出口门禁、§1 阶段总览
> 功能规格：`DevPrompt-AI-功能清单.md` F-801 / F-802 / F-803 / F-804 / F-805
> 目录权威：`DevPrompt-AI-项目架构文档.md` §4.8 / §5.1、§D 环境自检清单 13 项
> 本 spec 是既定任务清单的执行化增量描述；**与宪法冲突时以宪法为准并暂停上报**。

## Why

阶段七（整体验收与交付）是项目最后一个阶段，当前状态 **⬜ 未开始**。主要缺口：

- **F-801 第二段（排序准确率）门禁未达标**：LLM 路径实测 58/100 = 58% ＜ 80%（`eval/recall/report-ranking-2026-10-11.md`）。2026-10-11 曾裁「方案甲」（LLM 决策转正、Jev dormant）；**项目所有者 2026-10-14 决定改走 Jev 路径重测以真正满足门禁**，但 `TYPESAFE_API_KEY` 当前未配置 → Jev 路径**输入校验不通过**。
- **F-804 恢复一致性测试**无落地证据（`tests/` 无对应用例）。
- **F-805 成本明细**未输出（仅内部累计 `cost_tokens`）。
- **覆盖率未实测**（`pyproject` 无覆盖率工具），T7-1「≥70%」无法判定。
- **工程/文档漂移**：`pyproject` 仍残留 `aiomysql`/`PyMySQL`（存储已于 2026-10-07 定稿 SQLite）；`app.py` 未挂载 `frontend/dist`，无法单端口交付；审查报告 中等 8/9/11/12 + 轻微 16 条文档清理项未完成。

## What Changes

- **新增 Jev 门禁执行路径（T7-Jev，阶段七第一道门）**：启用 `jev` extra（`typesafe-sdk`）、配置 `TYPESAFE_API_KEY`，用 `JevDecider` 重跑 F-801 第二段排序准确率实测，出具报告（逐条明细 + 指标来源标注 + 失败案例分析）。**达标（≥80%）前阶段七不得收口（T7-8 阻塞）**。
- **T7-1 单测收口**：SHOULD-10 必测边界全覆盖 + 覆盖率 ≥70%；**新增 dev 依赖 `pytest-cov`**（MUST-04：1–4 级无等价覆盖率能力，coverage.py/pytest-cov 为标准方案，需同步登记技术栈版本表）。
- **T7-2 F-804 流程恢复一致性测试**：mock 决策层 + 固定种子下，两形态（HTTP `POST /optimize`→`GET /result`；resume：SSE 中断改 `GET /result` / 反问后再拉取）逐项对照。
- **T7-3 F-805 成本监控验收**：输出单次优化 token 明细（Jev 与 LLM 分别计）；`state` 超限截断而非报错且有日志。
- **T7-4 CI 六门禁收口**（MUST-29）：Ruff Lint/Format、mypy、pytest、前端 tsc/ESLint、架构约束、契约冒烟全绿；无 `--no-verify`。
- **T7-5 §D 13 项环境自检全清单**逐一通过（含 `GET /api/v1/health`）。
- **T7-6 文档清理提交**（单独 `docs` 提交）：中等 8/9（错误码表 5 处不符、§3.1 示例误用 4001）、中等 11/12（Web 一期二期冲突、store 职责混用）、轻微 16 条（命名/章节号/冗余/锚点失效）；技术栈版本表口径修正（Playwright/structlog **实际未采用**，非「未登记」）；**`pyproject` 移除冗余 `aiomysql`/`PyMySQL`（BREAKING：依赖清单变更）**。
- **T7-7 打包与部署**：`uv build` 出 wheel；`app.py` 挂载 `frontend/dist`（`StaticFiles` + SPA 回退）实现**单端口**托管；健康检查失败回滚策略；L1/L2/L3 数据向后兼容确认。
- **T7-8 阶段七收口**：出口门禁全绿 + 五文档同步 + 真源 §1 阶段七状态更新 + §13 追加变更记录。

## Impact

- Affected specs: F-801（检索质量实测）、F-802（冒烟）、F-803（核心单测）、F-804（恢复一致性）、F-805（成本监控）；MUST-25 / MUST-29 / MUST-04 / MUST-24b
- Affected code: `src/devprompt_ai/interfaces/api/app.py`（挂载 dist）、`pyproject.toml`、`tests/`（新增 F-804 用例、覆盖率）、`eval/recall/`（Jev 重测报告）、`scripts/`（如需打包/自检脚本）、`frontend/`（无功能改动）
- Affected docs: `DevPrompt-AI-实施真源文档.md`（§1 状态、§8.4、§13）、`DevPrompt-AI-功能清单.md`（F-801/F-803/F-804/F-805）、`DevPrompt-AI-技术栈文档.md`（版本表）、`DevPrompt-AI-项目架构文档.md`（如需）、`DevPrompt-AI-文档审查报告.md`

## ADDED Requirements

### Requirement: Jev 决策层启用与 F-801 第二段重测（阶段七阻塞门）

系统 SHALL 在 `TYPESAFE_API_KEY` 就绪时启用 `JevDecider`（`jev-1.13.0`，禁别名 MUST-12），并以 Jev 路径重测 F-801 第二段排序准确率，出具含逐条明细与指标来源标注的报告。Jev 路径不达标或输入缺失时，阶段七不得宣告收口。

#### Scenario: key 就绪并达标

- **WHEN** `uv sync --extra jev` 且 `TYPESAFE_API_KEY` 配置完成，运行 F-801 第二段实测
- **THEN** 报告标注为「Jev 排序准确率」，含逐条明细与失败案例；指标 ≥ 80% 时 G1 门禁通过

#### Scenario: key 缺失（输入校验不通过）

- **WHEN** `TYPESAFE_API_KEY` 为空时尝试运行 Jev 重测
- **THEN** 记 `decider.switched`（reason=`jev-no-api-key`）并**停止**：输出待确认项（需用户提供 key），**不得**以 LLM 结果冒充 Jev 指标，不得伪造达标结论

#### Scenario: Jev 路径实测不达标

- **WHEN** Jev 重测结果 < 80%
- **THEN** 触发 MUST-25 决策树（甲/乙）并**上报用户裁决**，不得含糊继续；阶段七 G1 门禁不通过

### Requirement: 核心单元测试收口与覆盖率（T7-1 / F-803）

系统 SHALL 覆盖 SHOULD-10 规定的必测边界（加权总分含手工验算、双阈值四情形、反问护栏与逃生、无具体未知零提问、偏好更新与裁剪、候选集条数硬约束、事实取证七项、Zod 拒绝畸形响应），并实测后端核心代码覆盖率 ≥ 70%。

#### Scenario: 覆盖率达标

- **WHEN** 运行 `uv run pytest --cov`（pytest-cov）
- **THEN** 覆盖率报告落盘且总覆盖率 ≥ 70%；必测八项均有对应用例

### Requirement: 流程恢复一致性测试（T7-2 / F-804）

系统 SHALL 在同一 mock 决策层 + 固定种子场景下，对「HTTP 路径」与「resume 重复执行路径」两条路径所得快照逐项对照，验证内容与评分一致性。

#### Scenario: 两路径一致

- **WHEN** 同一 project_dir/原句/偏好/决策层配置经两路径各执行一次并取快照
- **THEN** ① 三套方案正文逐套 diff 为空；② ranking 视图 `fit/pref/total/confidence/gap/marked/reason` 七字段逐字段相等；任一不符即 F-804 不通过并有明确原因说明

### Requirement: 成本监控验收（T7-3 / F-805）

系统 SHALL 输出单次优化的 token 消耗明细（Jev 与 LLM 分别计）；`state` 体积超限时截断并记录日志，而非报错。

#### Scenario: 成本明细与截断

- **WHEN** 执行一次优化并检查成本明细
- **THEN** 输出 token 消耗与来源（Jev/LLM）；构造超限 state 时发生截断并留有 `state.truncated` 日志

### Requirement: CI 六门禁全绿（T7-4 / MUST-29）

系统 SHALL 通过六项门禁：Ruff Lint + Format、mypy、pytest、前端 tsc + ESLint、架构约束检查、契约冒烟测试。

#### Scenario: 门禁全绿

- **WHEN** 本地复跑六项命令（与 `.github/workflows/ci.yml` 一致）
- **THEN** 全部退出码 0；提交历史无 `--no-verify` 记录

### Requirement: 环境自检清单 13 项（T7-5）

系统 SHALL 逐一通过架构文档 §D 的 13 项环境自检（Python 版本 / 依赖 / rg / ctags / LLM 配置 / 后端启动 / Jev 配置 / 前端依赖 / 前端启动 / 健康检查 / Lint / 类型检查 / 测试）。

#### Scenario: 13 项通过

- **WHEN** 按 §D 顺序执行 13 项检查
- **THEN** 13 项全部符合期望值

### Requirement: 文档清理（T7-6）

系统 SHALL 一次性完成审查报告遗留的文档清理项：中等 8/9/11/12 与轻微 16 条；技术栈版本表口径修正（Playwright/structlog 标注为**未采用**而非「未登记」）；`pyproject` 移除冗余 `aiomysql`/`PyMySQL`。

#### Scenario: 文档清理提交

- **WHEN** 提交 `docs` 变更
- **THEN** 命名/章节号/冗余/锚点问题消除；四份 CI 清单仅保留 MUST-29 一份权威；`pyproject` 与 SQLite 存储定稿一致

### Requirement: 打包与单端口部署（T7-7）

系统 SHALL 支持 `uv build` 产出 wheel，并由 FastAPI 单端口托管 `frontend/dist`（`StaticFiles` + SPA 回退），提供健康检查失败回滚策略，且 L1/L2/L3 数据向后兼容。

#### Scenario: 单端口演练

- **WHEN** 生产构建前端后在 FastAPI 单端口启动
- **THEN** 页面与 `/api/v1/*` 均可访问；`uv build` 产出 wheel；回滚路径可执行且数据可读

### Requirement: 阶段七收口（T7-8）

系统 SHALL 在全部出口门禁通过后更新真源 §1 阶段七状态为 ✅、§13 追加变更记录，并同步五份文档与实现一致。

#### Scenario: 收口

- **WHEN** 全部门禁通过
- **THEN** 真源 §1 阶段七 ⬜→✅；§13 记录裁定与验证数据；五文档与代码一致

## MODIFIED Requirements

### Requirement: 阶段七出口门禁中的 F-801 第二段（保持 ≥80%，仅改指标来源）

F-801 第二段 SHALL 以 **Jev 路径**实测并满足 ≥ 80%（不再以 LLM 路径代偿）。**理由**：项目所有者 2026-10-14 裁决「推进 Jev 获批并重测」；2026-10-11 的「方案甲」（LLM 决策转正、Jev dormant）在本轮不再作为达标依据，Jev 恰为 MUST-25 原文要求的最终指标来源。

### Requirement: 后端开发依赖

`pyproject.toml` 的 `[project.optional-dependencies].dev` SHALL 增加 `pytest-cov`，并同步 `DevPrompt-AI-技术栈文档.md` 版本表。

## REMOVED Requirements

### Requirement: MySQL 相关依赖

**Reason**: 存储已于 2026-10-07 定稿为 SQLite 单文件（真源 §13），`aiomysql`/`PyMySQL` 无代码引用且与技术栈 §4.8 不符。

**Migration**: 从 `pyproject.toml` 移除两项；更新 `uv.lock`（`uv sync`）；确认无 import 引用后再提交。
