# HANDOFF · DevPrompt AI 天枢化改造

> 更新时间：2026-11-08（阶段 3–10 全部接线完成，基线 `1268 passed / 9 skipped`）
> 验证基线：`ruff` / `format` / `mypy --strict` / `check_architecture.py` / 前端 build 全绿。
> 本文档面向「接手的下一位工程师或 AI 会话」，说明已完成什么、哪些还没接线、下一步具体改哪里。

---

## 一、总体状态

把天枢 harness 的可借鉴设计落地到本项目，共 12 个工作流 + 后续接线。当前状态：

| 类别 | 状态 |
|---|---|
| 运行时层（多端会话服务） | ✅ 已交付并接线 |
| 终止、预算、收敛 | ✅ 已交付，收敛已接主循环 |
| 压缩引擎 | ✅ 已交付，已接 `build_context` |
| 上下文分层（四层提示/delta） | ✅ 已接 `_assemble_context`（delta 为提示性增量，见 §三·阶段3 备注） |
| 契约锚点、认知账本、块配额 | 🔶 参数与拼接已就绪，账本默认关闭 |
| 工具输出治理 | ✅ 已接 trace 通道（摘要 + 落盘 + 回读 API） |
| 多模型（池/路由/主备/bandit） | ✅ purpose 路由 + bandit + 主备 + F10 热切换（端点+前端控件）已接；`multi_model_routing=True` 单候选退化 |
| 观测（检测器/归属/AQS） | ✅ 检测器/归属/策略映射/绝对压力/token 账本已接 |
| 子 agent | ✅ 工单/调度/worker/delegate 动作已接（execute 为确定性汇总） |
| 仓库智能 | ✅ 索引/影响半径已接；BM25+RRF+路径重排（只调序）与 physarum 边权已接；图默认关闭 |
| 权限门 | ⛔ 明确不做（用户决定） |
| 真实 worktree 写工 | ⛔ 只保留参数构造（用户决定） |
| team/council | ✅ 纯调度接入 `_act_delegate`（分池/占位/去重；不调 LLM） |
| 评测基线 | ⛔ 跳过（不消耗额度） |

---

## 二、已完成的关键落点

### 1. 运行时层（新增 `src/devprompt_ai/runtime/`）

| 文件 | 职责 |
|---|---|
| `events.py` | 事件总线：先落库再扇出，seq 由存储层分配，慢订阅者丢帧 |
| `runs.py` | RunManager：独立 task 执行，与 HTTP 连接解耦；取消有 6s drain |
| `sessions.py` | 执行器池：同一会话单执行体 + 空闲 TTL |
| `interventions.py` | 审批/提问：第一应答获胜 |
| `coordinator.py` | 委派调度：分池信号量 + 文件占位 |
| `streams.py` | SSE 帧编码（`id: seq`） |
| `lock.py` | 单写者文件锁（心跳 + 过期接管，默认 120s） |
| `bootstrap.py` | 装配单例；启动时收敛孤儿 run |

新增 8 张表：`runs` / `run_events` / `interventions` / `artifacts` / `repo_symbols` / `repo_edges` / `routing_stats` / `token_ledger`。

新增 5 个 API（`interfaces/api/runtime_routes.py`）：
`POST /api/v1/runs`、`GET /api/v1/sessions/{id}/stream?since=N`、`POST /api/v1/interventions/{id}/answer`、`POST /api/v1/runs/{id}/cancel`、`GET /api/v1/events`。

### 2. 控制流

- `domain/agent/stop_reason.py`：12 种终止原因 + 分类；主循环五条退出路径全部写入 `stop_reason`
- `domain/agent/finish_gates.py`：natural-finish 六道闸（**仅模块 + 单测，未接入收尾路径**）
- 主循环已接：no-answer 闸、wedged 检测（连续 4 步同动作且事实无增长）、run 级看门狗（900s）
- `harness/retry.py`：指数退避 + 共享 RetryBudget；`llm.py` 已设 `max_retries=0`
- `harness/abort.py`：`reject_on_abort`（**未替换现有等待点**）
- 分层超时：probe/rank 30s、generate 120s

### 3. 收敛

`domain/agent/phase_convergence.py` 已替换旧三判据：
七信号 + 五套相位权重 + 分数×轮次双门槛 + 五道否决 + reasoningActive。
`service._phase_for` 按最近动作映射阶段。

### 4. 压缩与上下文

已交付模块：`tokens / budget / compact_policy / compact_economics / advisor / compactor / micro / collapse / prune / stale / summary / task_contract / prompt_layers / ledger`。

已接线：
- `build_context` 支持 `context_window / estimated_tokens / cache_kind`，按 `plan_compaction().budget_ratio` 缩放四层预算，current 层永不压
- 新增 `ledger_block` 与 `tail_anchor`，由 `compose_history` 按「历史 → 账本 → 锚点」拼接
- 记忆块经 `fit_blocks` 按 `project_memory=3000` 硬裁
- `harness/overflow.py`：超窗压一次重发（**未接调用点**）
- `harness/summarize.py`：LLM 摘要 + 后检 + 9 段 handoff 兜底（**未接调用点**）

开关（默认均关闭）：
- `context_ledger_enabled`：认知账本注入
- `repo_graph_enabled`：符号图与影响半径

### 5. 多模型

- `domain/model/{registry,routing,task_inferrer}.py`
- `harness/{model_pool,fallback}.py`；`llm.py` 客户端改为 LRU 池（键含 model/base_url/api_key）
- **未接**：`pick_model` 路由、`FallbackClient` 主备、`routing_stats` bandit、会话模型热切换

### 6. 子 agent

- `domain/agent/{work_order,delegation,profile_registry}.py`
- `runtime/coordinator.py`、`harness/worker_session.py`
- `AgentAction.DELEGATE` 已加入枚举与 `NextActionOutput.action`，提示词有使用边界
- `service._act_delegate` 已实现：构造 `WorkOrder` → `run_read_worker` → 结果写 `session.data["delegation"]`
- 当前 `execute` 是**确定性汇总**（不调 LLM）；接真实子 agent 只需替换 `execute`
- `harness/worktree.py` 只有参数构造，不执行 git

### 7. 仓库智能

`harness/{pygraph,repo_indexer}.py`、`domain/retrieval/impact.py`、`memory/repo_index.py`。
`service._attach_impact` 已接，受 `repo_graph_enabled` 控制（默认 False）。

**性能教训**：首次全量索引 800 文件会把测试从 28s 拖到 3m20s，因此默认关闭；开启前先实测。

### 8. 提示词

`domain/prompt_guard.py`：
- `EVIDENCE_HYGIENE`（已注入 FACTS/NEXT_ACTION）
- `EVIDENCE_SCOPE` / `EXTERNAL_SOURCE_VERIFICATION`（已注入 FACTS_SYSTEM）
- `DELIVERY_CONTRACT`（已注入 NEXT_ACTION_SYSTEM）
- `MODEL_FAMILY_NOTES` / `family_note()`（2026-11-08 已接 `llm._instructions`）

### 9. 前端

- `api/protocol.ts`、`hooks/useRunStream.ts`、store `applyRunEvent`
- OptimizePage：先 `fetchLastSeq → startRun → 订阅`；旧 `/optimize/stream` 保留为**启动前失败**的回退
- `openapi.json` 已更新为 23 路径 / 26 操作（+artifact 回读、+会话模型热切换）

### 10. 文档与宪法

- 架构文档 §4.8 已登记 `runtime/` 与新增模块
- `AGENTS.md` 新增 MUST-11b/11c/11d/11e

---

## 三、剩余工作（按依赖顺序）

### 阶段 3 收尾：B1–B4 两段式提示 —— ✅ 已完成（2026-11-08）

- `build_context` 新增 `delta_block`（历史 → 增量 → 账本 → 锚点，顺序固定）
- `service._render_context_delta`：`render_delta` 渲染 `<context-update seq="N">`，跨轮快照存 `session.data["prompt_layers"]`（`optimize` 每轮重建 data，已显式带走）
- B18 `family_note` 经 `harness/llm.py::_instructions` 进 system prompt（未知厂商不插）
- **备注**：本项目每次 LLM 调用都是无状态单发，delta 只作「自上次以来的变化」提示（无变化时自闭合），不是传输级增量替换；会话改为携带消息历史后需升级

### 阶段 4：工具输出接线（C1–C9）—— ✅ 已完成（2026-11-08）

- 拦截点在 `harness/trace.py`（唯一通道层）：`_governed_output` 超阈值 → `output_store.persist` 落盘（落盘前 redact）→ `summarize_output` 摘要（成功留尾 / 失败留头+错误锚段+尾）→ `with_footer` 回读指针
- 摘要行数按 MUST-19 的 20 行上限反推（success=18 / failure_budget=9 + footer 1 行）
- 回读：`GET /api/v1/artifacts/{id}`（`runtime/artifacts.py` 封装 `output_store.read_by_id`，id 为 sha256 前 24 位十六进制）；openapi 计数 **22 路径 / 25 操作**
- `output_store.cleanup()` 已挂 `build_default` 启动清理

### 阶段 5：观测接线（E3/E4/E9/E10/E11、H5）—— ✅ 已完成（2026-11-08）

- `_pressure` 改为 `max(相对比例, 上下文绝对占用)`；`_assemble_context` 把估算值写入 `session.data["context_tokens"]`
- `_record_sensorium` 调 `derive_strategy`，effort/breadth 落 `session.data["strategy"]`（shadow）
- `DetectorHook` 挂 post_tool（死路优先于自检；`needs_self_verify` 加最小连击数 3，1~2 步只读是正常节奏不提醒）；`is_dead_end` 依赖步骤带 FAILED outcome，当前主循环恒记 OK，**分支待命**
- `gate.py` 接 `evaluate_attribution`：影响半径与 file 断言求差集（`service._build_attribution`），非 GREEN → YELLOW 披露 + 撤销推荐
- `harness/llm.py::_record_usage` 捕获 prompt/completion 拆分；`_finish_turn` 每轮一次写 `token_ledger`（零用量不记）

### 阶段 6：多模型接线（G2–G6、G9、G10、F10）—— ✅ 已完成（2026-11-08）

- `chat_structured`/`chat_with_tools` 增 `purpose` 参数（probe/rank/generate/summarize/decide）；路由、主备、按模型超时、落账全部收敛在这一处
- 候选来自 settings 注册表（`harness/model_candidates.py`，60s 缓存，键含配置 hash）；bandit（`pick_model`）读 `routing_stats`，每次调用落账
- 主备按注册顺序（`FallbackClient`），只对可重试错误降级（复用 `classify_llm_failure` 口径），鉴权/额度直接抛
- 摘要走 summarize 槽（最低档候选）；F10 热切换：`POST /sessions/{id}/model` 写 `session.data["model_override"]` + 前端切换控件；openapi **23 路径 / 26 操作**
- `multi_model_routing=True` 默认开，单候选退化为现状（行为对等由「候选只有 1 个时永远选它」保证）

### 阶段 7：长会话（H1/H2/H4）—— ✅ 已完成（2026-11-08）

- 每 5 步 checkpoint：`run_agent_loop` 经 `checkpoint_sink`（bootstrap 注入 `bus.append`）落 `run_events`
- `run_events` 增 `checksum` 列（写入即算，旧库 `ALTER` 补列）；启动 `verify_checksums` 校验，不匹配告警不删改
- 记忆沉淀：静默中断（`_abort_quietly`）补 `_finish_turn`，turn_memory/L2 笔记不再漏落

### 阶段 8：检索接线（I1–I3、I6、I4/I5）—— ✅ 已完成（2026-11-08）

- `reorder_by_lexicon`（`candidates.py`）：BM25 名次 + 符号分名次 RRF 融合后乘 `path_weight`，**只调序不减候选**（MUST-09）；刻意未用会丢候选的 `salience.rerank`
- physarum：`repo_edges.weight/updated_at` 列（旧库自动补列），`_attach_impact` 强化访问边并按 (hops, -weight) 排序；dt 按小时计（tau=300 ≈ 半衰期 8.7 天）
- repo 图自动探测：既有 Python 项目标记检查（无 pyproject/setup 跳过）已覆盖「有标记才建图」，配置门保持默认关（性能教训）
- AQS 提前折叠：`_suppress_ask` 已在 `_act_probe` 接线（核实，无需改动）

### 阶段 9：team 纯调度（K6）—— ✅ 已完成（2026-11-08）

- `DelegationCoordinator`（分池信号量+文件占位+去重）接入 `_act_delegate`：工单过三道闸再执行，被拒降级为通知 + `delegation.rejected` 事件，不阻断主流程
- **不新增 LLM 调用**（execute 仍为确定性汇总）

### 阶段 10：文档与验收 —— ✅ 已完成（2026-11-08）

- 架构文档 §4.8：删 `probes.py`，补 retrieval/agent/delivery/harness/runtime 新模块；`domain/decision/probes.py` 已删除（零引用孤儿，用户批准）
- 全量测试 + 架构守卫 + 前端 typecheck/build 全绿

---

## 四、关键决策（不要回退）

| 决策 | 结论 |
|---|---|
| 权限门 D1–D5 | **不做**（用户明确） |
| 真实 worktree 写工 | **不做**，只保留参数构造 |
| team/council | **纯调度**，不调 LLM |
| 无消费方模块 | **维持不接**（用户 2026-11-08 裁定：本项目不需要消费方）——`tool_registry`/`tool_batch`/`task_inferrer`/`artifact_store` 四个模块的孤儿状态是终态，后续会话不得再尝试接线 |
| `runtime/model_switch.py` | **不建**（用户 2026-11-08 裁定：热切换已由端点+路由链等效达成，不建空壳） |
| 多用户/多租户 | **暂不做**（用户 2026-11-08 裁定）：新增逻辑不引入用户维度泛化，`user_id` 保持默认 "local" 透传 |
| 依赖许可 | **放宽**（用户 2026-11-08 裁定）：MUST-04「最后手段」约束解除；出现确有优势的库可提议引入 |
| 评测基线 | **跳过**，`GAP_SOFT=0.25` 未回测 |
| `claim_strict` | 默认 **True**（BREAKING） |
| API 拆分 | `/runs` + `/sessions/{id}/stream` 为正式路径；旧 `/optimize/stream` 保留兼容 |
| 符号图 | 默认关闭（性能） |
| 认知账本 | 默认关闭（避免无谓 prompt 变化） |

---

## 五、环境与验证命令

```powershell
cd 'd:\Works\DevPrompt AI'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m ruff format --check src tests
.\.venv\Scripts\python.exe -m mypy src/devprompt_ai
.\.venv\Scripts\python.exe scripts/check_architecture.py

cd frontend
pnpm typecheck
pnpm build
```

注意：
- 不要用 `Set-Content` 改源码（编码风险），用编辑工具
- `interfaces/` 不得 import `memory/`（架构守卫会拦，artifact 回读必须经 runtime）
- 新增事件名必须登记到 `observability/logging.py::EVENT_NAMES`

---

## 六、接手提示词

> 天枢化接线已全部收口（阶段 3–10 完成，基线 1268 passed）。下一步候选：①多模型真实冒烟（两个供应商 Key 验证主备切换与 bandit 分布）②`is_dead_end` 待命分支激活（动作失败开始落账）③eval 基线回测（需供应商额度，业主裁定暂缓）。

---

## 七、已知风险

1. **待命分支**：`is_dead_end` 依赖步骤带 FAILED outcome，主循环目前恒记 OK，该检测暂不触发
2. **多模型未经真实冒烟**：路由/主备/热切换全部有单测覆盖，但没有双供应商真实调用证据（bandit 冷启动时按注册顺序，探索占 10%）
3. **physarum dt 口径**：衰减按小时计（tau=300），若访问节奏以「分钟」计衰减可忽略——语义未经实测标定
4. **默认值变更**：`claim_strict=True` 与 `GAP_SOFT=0.25` 属 BREAKING，提交信息需标注
5. **符号图性能**：全量索引成本高，开启前务必实测目标仓库规模
6. **回退路径**：前端保留旧流式回退，W12 验收后应删除该分支
7. **测试依赖真实行为**：接线阶段会触及多处断言，必须「改一块、验一块」
