# 弃用 CLI、全面转向 Web-only 架构 · 实施计划

> 2026-10-10 · 批准人=项目所有者（本次 /plan 会话明确授权：提前实现 Web HTTP + 全量改写所有文档）
> 性质：规格级 **BREAKING** 变更（废除双形态交付，宪法附则流程留痕）

---

## Summary

1. 彻底删除 CLI 表现层（源码/测试/入口/依赖）；
2. **提前实现阶段六的 FastAPI Web HTTP 层**（service 已就绪，HTTP 为薄壳），消除「无可用形态」空窗；
3. 全量改写 14 份文档为 Web-only 口径（含历史记录，用户明确选择覆盖历史留痕先例）。

## Current State（探索实证）

| 项 | 现状 |
|---|---|
| CLI 源码 | `src/devprompt_ai/interfaces/cli/`（main.py / commands.py / prompts_flow.py / render.py / __init__.py，共 5 文件） |
| CLI 测试 | `tests/cli/test_commands.py`（唯一引用 typer.testing） |
| 依赖 | pyproject.toml：`typer`、`rich`（rich 无其他消费者）+ `[project.scripts] devprompt` 入口 |
| 隔离性 | `scripts/`、`domain/`、`service.py`、`harness/` 均零 CLI 依赖（依赖方向单向保证） |
| Web 现状 | FastAPI/uvicorn 已在依赖中，但 **HTTP 层一行未写**（原阶段六排期）；service 六方法（optimize/ask_followup/confirm/feedback/get_preference/resume）已就绪 |
| 文档引用面 | 活跃规格 6 份（AGENTS.md×4、技术栈×24、功能清单×26、架构文档×26、真源×22、审查报告×1）+ 历史 8 份（阶段二/三/四计划、spec×2、workbuddy×2、eval 报告×2）≈ 294 处 |

## Proposed Changes

### A. 代码删除（变更类型：删除）

| 对象 | 动作 |
|---|---|
| `src/devprompt_ai/interfaces/cli/`（整目录 5 文件） | 删除 |
| `tests/cli/`（test_commands.py） | 删除 |
| pyproject.toml `dependencies` 中 `typer`、`rich` | 删除 |
| pyproject.toml `[project.scripts]` 段 | 删除 |
| `uv.lock` | `uv sync` 重新生成 |

### B. Web HTTP 层提前实现（变更类型：新增，薄壳原则：HTTP 只做「参数收拢→调 service→渲染」，零业务逻辑）

新增 `src/devprompt_ai/interfaces/api/`：

| 文件 | 职责 |
|---|---|
| `app.py` | FastAPI 实例、CORS（`cfg.cors_origins`）、统一异常处理（DevPromptError/ProcessError/TimeoutError → `{code,message,data,request_id}`，不回传堆栈——MUST-19 CLI 等价条款平移） |
| `routes.py` | 端点定义（下表 9 个） |
| `health.py` | 环境自检逻辑（从待删除的 CLI commands.py 中迁移 doctor 检查项：rg/ctags/git/DB/llm_config） |
| `schemas.py` | Pydantic v2 请求/响应模型（`XxxRequest`/`XxxResponse` 命名） |

端点映射（全部透传既有 service 能力，不造假数据）：

| 端点 | service 调用 | 备注 |
|---|---|---|
| `GET /api/v1/health` | health.py 自检 | 阶段四 doctor 平移 |
| `POST /api/v1/optimize` | `optimize("local", project, sentence)` | 返回 FlowSnapshot；**禁重试**（MUST-15） |
| `GET /api/v1/progress/{flow_id}` (SSE) | 快照轮询（1s 间隔读 L1 快照推送） | 不引入新依赖；连接关闭即停 |
| `POST /api/v1/followup/{flow_id}` | `ask_followup` / `confirm`（含逃生 `!`、护栏裁决） | 请求体 `answers`/`escape`/`guardrail_action` 三模式 |
| `GET /api/v1/result/{flow_id}` | 快照读取 | |
| `POST /api/v1/feedback` | `feedback` | 阶段五 L3 接入前为透传当前实现 |
| `GET /api/v1/preference` | `get_preference` | 返回当前（初始）向量 |
| `PUT /api/v1/preference` | —（service 无 set） | 返回 `501` + code 9004，注明阶段五接入 |
| `GET /api/v1/history` | —（session store 无 list） | 返回 `501` + code 9004，注明阶段五接入 |
| `GET /api/v1/project/scan?project=` | 新增薄方法 `service.scan_project()`（仅透出符号表统计，复用 F-101 能力） | |

新增 `tests/api/test_routes.py`（httpx AsyncClient，复用既有 service Fake 注入模式，覆盖：optimize 200/反问 200/护栏分支/501 端点/异常统一结构/健康检查）。

**暂停点（执行中触发即停并上报）**：service 方法签名与端点映射不符、SSE 轮询与 L1 快照结构不匹配、CORS 配置语义歧义。

### C. 文档全量改写（14 份，用户选定「全量改写」覆盖历史留痕先例）

| 文档 | 改写要点 |
|---|---|
| `AGENTS.md` | 版本头 v1.2 + BREAKING 记录（批准人=项目所有者，2026-10-10）；MUST-10「双形态一致」整节重写为「单一 Web 形态」；MUST-15/16/26/28 及执行清单中 CLI 表述全部改 Web 口径 |
| `DevPrompt-AI-功能清单.md` | F-601 重定义为「Web API 端点」、F-602 重定义为「Web 交互界面（阶段六 UI）」（原 CLI 语义删除）；W2/W4 任务表、SHOULD 引用同步；变更记录追加 |
| `DevPrompt-AI-项目架构文档.md` | §4.8 删 `interfaces/cli/` 树、新增 `interfaces/api/`；§1.6/§1.8/附录 全部 Web 口径 |
| `DevPrompt-AI-技术栈文档.md` | §4.7 CLI 框架节删除；typer/rich 移出 §6.2 版本表；CLI 命令清单表→端点表；§摘要/§排除理由 同步 |
| `DevPrompt-AI-实施真源文档.md` | §1 阶段四状态注记（CLI 已删、HTTP 提前）；§9/§12 Web 口径；§13 变更记录（BREAKING + 批准人） |
| `DevPrompt-AI-文档审查报告.md` | 头部加 v1.2 注记后，正文 CLI 引用全量改写 |
| `doc-阶段/` 阶段二/三/四计划 ×3 | 全量改写为 Web-only 口径（CLI 任务改为对应 Web 等价描述或标注移除） |
| `.trae/specs/implement-phase3/phase4/` ×2 | 同上口径改写 |
| `.workbuddy/memory/` ×2 | CLI 相关条目改写为 Web 口径 |
| `eval/recall/` 报告 ×2 + README | 命令示例改为 HTTP 调用 |

### D. 提交策略

1. `feat(web): 新增 FastAPI HTTP 层并移除 CLI 形态`（BREAKING CHANGE footer：废除 CLI 双形态，批准人=项目所有者）——代码 A+B 合一提交（原子性：删除与替代同缝）
2. `docs: 全量同步 Web-only 口径`——文档 C 单独提交

## Assumptions & Decisions

- **D1**（用户已裁）：提前实现 Web HTTP，消除空窗期。
- **D2**（用户已裁）：历史文档全量改写，不留 CLI 原文。
- **D3**：`PUT /preference`、`GET /history` 在 L3（阶段五）接入前返回 501+9004——薄壳不造假数据。
- **D4**：SSE 用「1s 轮询 L1 快照」实现，不引入 WebSocket/新依赖（MUST-04）。
- **D5**：`rich` 确认无其他消费者（grep 实证）后删除；uvicorn 保留（Web 需要）。
- **D6**：前端 React UI（阶段六原排期）**不在本计划范围**——本次只提前 HTTP 层；UI 仍待后续阶段。

## Verification

1. `uv sync --frozen`（uv.lock 更新成功，typer/rich 消失）
2. `uv run ruff check . && uv run ruff format --check .`（零错误）
3. `uv run mypy`（零错误，93→~88 文件）
4. `uv run pytest -q`（全绿；CLI 测试移除、新增 API 测试）
5. `uv run python scripts/check_architecture.py`（依赖方向零违规）
6. **真实冒烟**：`uv run uvicorn devprompt_ai.interfaces.api.app:app --port 8000` → `curl /api/v1/health` 200 → `POST /api/v1/optimize`（DeepSeek 端到端，含反问 followup 调用）→ SSE progress 收到事件流
7. 全库 grep `typer|interfaces\.cli|devprompt optimize`（文档+代码）→ 仅剩 BREAKING 变更记录中的历史指称
