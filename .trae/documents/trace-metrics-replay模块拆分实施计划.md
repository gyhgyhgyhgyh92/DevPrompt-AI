# Trace / Metrics / Replay 三模块独立拆分实施计划

> 目标：把现有「可观测性」一体的实现拆成三个职责单一、可独立启用/配置/升级的模块。
> 已确认决策：**Replay = 确定性回放**（不真实调用 LLM/工具）、**Trace = 全量明文入库**（经你批准 MUST-19 例外）、**Metrics 告警 = 持久化告警历史**（不做外部推送）。
> 参考 DeerFlow 的架构思路：节点化执行、共享类型化状态、checkpoint/回放、生命周期与执行器分离（见文末参考）。

---

## 一、现状取证与拆分动因

| 现状 | 问题 |
|---|---|
| `domain/observability/trace_metrics.py` 同时做「事件投影 + 指标聚合」 | Trace 与 Metrics 耦合在一个纯函数里，无法独立升级 |
| `interfaces/api/observability_routes.py` 一个端点返回事件 + 轮次 + 指标 | API 契约耦合；任一模块改动都会破坏另外两个消费方 |
| 前端 `settings/observability/` 共用一份 `useSessionObservability` 数据 | Trace / Replay 共用数据模型，无法独立启用或替换 |
| `run_events` 只在 `RunManager`（HTTP `/runs`）路径写入 | 直接调用 `ForgeService.optimize` 的会话完全没有轨迹（实测旧会话 `last_seq=0`） |
| `harness/trace.py` 只产出 UI 动作卡片（脱敏、≤2000 字符） | 不是可回放的完整 Trace；无 LLM 请求/响应、无决策输入输出 |
| Replay 目前只是「沿时间轴播放已存事件」 | 不执行管线，无法做回归与版本对比 |
| 无指标阈值/告警存储设施 | 无法回答“系统是否健康”、无告警历史 |
| MUST-19 禁止原句/绝对路径入库与输出截断 | 与「完整记录输入输出」冲突（已由你批准全量明文入库） |

---

## 二、目标架构

```
┌────────────────────────── 共享契约（唯一跨模块依赖）──────────────────────────┐
│ domain/obs/contract/  TraceEvent / TraceEnvelope / TraceQuery / Ports / 版本号 │
└───────────────┬───────────────────────┬───────────────────────┬──────────────┘
                │                       │                       │
        ┌───────▼────────┐      ┌───────▼────────┐      ┌───────▼────────┐
        │ Trace 模块      │      │ Metrics 模块    │      │ Replay 模块     │
        │ 采集 + 存储 + 查询│      │ 聚合 + 阈值 + 告警│      │ 确定性回放 + 对比 │
        └───────┬────────┘      └───────┬────────┘      └───────┬────────┘
                │ 只写 TraceStore        │ 只读 TraceReader       │ 只读 TraceReader
                ▼                       ▼                       ▼
        memory/trace_store.py   memory/metrics_alert_store.py  memory/replay_store.py
```

依赖规则（扩展 MUST-06）：
- 三模块之间**不互相 import**；只依赖 `domain/obs/contract/`。
- 模块间通信只用标准契约与 `TraceListener` 事件（`trace.completed`），不共享内部实现。
- SQL 仍只允许出现在 `memory/`；三模块的存储实现分别是 `memory/trace_store.py`、`memory/metrics_alert_store.py`、`memory/replay_store.py`。
- 应用编排放 `src/devprompt_ai/obs/{trace,metrics,replay}_service.py`，由 `obs/registry.py` 按配置装配；不修改 `ForgeService` 的业务逻辑，只注入采集器。

目录（新增/修改）：

```
src/devprompt_ai/
├── domain/obs/
│   ├── __init__.py
│   ├── contract/
│   │   ├── __init__.py
│   │   ├── trace.py          # TraceKind/TraceStatus/TraceEvent/TraceEnvelope/TraceBatch
│   │   ├── query.py          # TraceQuery/AggregateQuery/Page/Cursor
│   │   ├── ports.py          # TraceStore/TraceReader/TraceCollector/TraceListener/ReplayExecutionPort
│   │   └── version.py        # TRACE_SCHEMA_VERSION / METRICS_SCHEMA_VERSION / REPLAY_SCHEMA_VERSION
│   ├── trace/tree.py         # 调用链树构建、分页、preview 截断（纯函数）
│   ├── metrics/
│   │   ├── aggregate.py      # 指标聚合模型与序列化（纯函数）
│   │   ├── rules.py          # 阈值规则评估（纯函数）
│   │   └── alerts.py         # 告警去重/冷却/恢复（纯函数）
│   └── replay/
│       ├── playback.py       # 按 call_key 取录制结果（纯逻辑）
│       ├── engine.py         # 回放状态机（校验事件链、驱动 ExecutionPort）
│       ├── compare.py        # 单 Trace 自比对 / 双 Trace 版本对比
│       └── normalize.py      # 快照归一化（去掉时间/ID 噪声）
├── memory/
│   ├── obs_schema.py         # trace_events / metrics_alerts / replay_runs / replay_nodes DDL
│   ├── trace_store.py        # 写入/查询/聚合 SQL
│   ├── metrics_alert_store.py
│   └── replay_store.py
├── obs/
│   ├── __init__.py
│   ├── trace_service.py      # 采集生命周期、查询、导出
│   ├── metrics_service.py    # 聚合查询、告警评估、告警历史
│   ├── replay_service.py     # 创建回放/对比任务、查询结果
│   ├── registry.py           # 模块装配、启用开关、TraceListener 注册
│   └── settings.py           # 模块配置读取（从 AppConfig）
├── harness/obs/
│   ├── trace_collector.py    # 队列 + 批量写入 + 失败降级（实现 TraceCollector）
│   ├── traced_runner.py      # 包装 CommandRunner：记录 tool.call/result（全量 argv/stdout/stderr）
│   ├── traced_reader.py      # 包装 FileReader：记录 file.read（全量内容）
│   ├── traced_generator.py   # 包装 GeneratePort：记录 llm.request/response + request_hash
│   ├── traced_decider.py     # 包装 DecisionPort：记录 decision.request/response
│   └── recorded_ports.py     # 回放用：RecordedRunner/Reader/Generator/Decider
└── interfaces/api/
    ├── obs_trace_routes.py
    ├── obs_metrics_routes.py
    ├── obs_replay_routes.py
    └── obs_common.py         # ApiResponse 兼容 + 分页/游标公共模型
```

> 删除：`domain/observability/`、`interfaces/api/observability_routes.py`（由三模块替代）。

---

## 三、共享契约（唯一跨模块接口）

### 3.1 Trace 事件模型

```python
class TraceKind(str, Enum):
    TURN_START = "turn.start"; TURN_END = "turn.end"
    ACTION_START = "action.start"; ACTION_END = "action.end"
    DECISION = "decision.request"; DECISION_RESULT = "decision.response"
    LLM = "llm.request"; LLM_RESULT = "llm.response"
    TOOL = "tool.call"; TOOL_RESULT = "tool.result"
    FILE = "file.read"
    GATE = "gate.evaluate"
    SENSORIUM = "sensorium.snapshot"

@dataclass(frozen=True, slots=True)
class TraceEvent:
    event_id: str            # uuid4
    trace_id: str            # 一次 turn 一个 trace：f"{session_id}:{turn_index}"
    session_id: str
    turn_id: str
    turn_index: int
    run_id: str
    seq: int                 # trace 内单调递增（写入端分配）
    parent_id: str           # 调用链父事件；根为空
    kind: TraceKind
    name: str                # 节点名（如 retrieve/probe/generate/llm.generate_single）
    status: str              # ok/failed/skipped
    started_at: str          # ISO8601 UTC 毫秒
    ended_at: str
    duration_ms: int
    input: dict[str, Any]    # 全量明文（已按用户批准）
    output: dict[str, Any]   # 全量明文
    error: dict[str, Any]    # type/message/code（无堆栈）
    attributes: dict[str, Any]  # model_id/prompt_version/code_version/call_key/input_hash/size_bytes
    schema_version: int
```

- **call_key**（回放寻址）：
  - LLM/决策：`sha256(kind|name|model_id|system|user|params_json)`
  - 工具：`sha256(argv_without_route_key|sorted(env)|cwd)`
  - 文件：`sha256(path)`
- **input_hash**：`turn.start` 记录 `sha256(sentence + project_root + inherited_target + clarifications)`，用于判断两条 Trace 是否同一输入。
- **preview 规则**：列表接口只返回 `preview`（≤500 字符），`GET /events/{event_id}` 返回全量；存储永远全量。

### 3.2 标准查询/分页

```python
@dataclass(frozen=True)
class TraceQuery:
    session_id: str = ""; trace_id: str = ""; kind: str = ""
    from_ts: str = ""; to_ts: str = ""
    cursor: int = 0            # seq 游标，0 表示从头
    limit: int = 200

@dataclass(frozen=True)
class AggregateQuery:
    session_id: str = ""; trace_id: str = ""
    from_ts: str = ""; to_ts: str = ""
    group_by: Literal["kind", "name", "model", "turn", "status"] = "kind"
    bucket: Literal["none", "minute", "hour", "day"] = "none"
    percentiles: tuple[int, ...] = (50, 95, 99)
    limit: int = 500
```

所有模块响应均带 `schema_version`；只增字段、不改语义；新增字段必须给默认值。

---

## 四、Trace 模块

### 4.1 采集点（覆盖直接调用，不依赖 HTTP）

| 采集点 | 事件 | 内容 |
|---|---|---|
| `ForgeService.optimize` / `ask_followup` 入口/出口 | `turn.start` / `turn.end` | 原句、project_root、继承 target、clarifications、最终 snapshot 摘要、input_hash |
| `run_agent_loop` 每步 | `action.start` / `action.end` | action、step index、决策输出、outcome、facts_passed、duration |
| `_act_retrieve/_act_probe/_act_generate/_act_reply/_act_deliver` | `action.start/end`（parent=step） | 输入参数、输出摘要（候选/事实/方案/门禁） |
| `TracedGenerator` 包装 `GeneratePort` | `llm.request` / `llm.response` | model_id、system/user 全文、temperature、raw response、解析结果、tokens、call_key |
| `TracedDecider` 包装 `DecisionPort` | `decision.request/response` | 方法名、完整入参、模型原始输出 |
| `TracedRunner` 包装 `CommandRunner` | `tool.call` / `tool.result` | 全量 argv、cwd、exit code、stdout、stderr、duration、call_key |
| `TracedReader` 包装 `FileReader` | `file.read` | 路径、全文内容、行数、duration |
| `_record_sensorium` | `sensorium.snapshot` | 六维 + score + quality |

- 包装器在 `build_default` 装配；测试实例默认 `NullTraceCollector`，既有测试零改动。
- `TracedRunner` 与现有 UI `TracingRunner` 可叠加：Trace 负责持久化，Tracing 负责进度卡片。
- **密钥脱敏**：写入前统一经过 `mask_secrets(input/output)`，对 `api_key`、`authorization`、`token`、`secret` 等键名做掩码；其余内容按用户批准保留明文。

### 4.2 写入策略

`harness/obs/trace_collector.py`：
- 有界队列（4096）+ 后台批量写入（每 50 条或 200ms flush），避免阻塞主链。
- `seq` 在写入端按 `trace_id` 分配；单 trace 内严格递增。
- 写失败：记 `trace.write_failed` 固定事件，Trace 标记 `status=partial`；**不阻断业务**（可观测性降级，UI 如实展示）。
- 关闭/进程退出：`flush()` 由 `build_default` 的 lifespan 调用。

### 4.3 存储 DDL（`memory/obs_schema.py`）

```sql
CREATE TABLE IF NOT EXISTS trace_events (
  trace_id TEXT NOT NULL, seq INTEGER NOT NULL, event_id TEXT NOT NULL,
  session_id TEXT NOT NULL, turn_id TEXT NOT NULL, turn_index INTEGER NOT NULL,
  run_id TEXT NOT NULL DEFAULT '', parent_id TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL,
  started_at TEXT NOT NULL, ended_at TEXT NOT NULL DEFAULT '',
  duration_ms INTEGER NOT NULL DEFAULT 0,
  input_json TEXT NOT NULL DEFAULT '{}', output_json TEXT NOT NULL DEFAULT '{}',
  error_json TEXT NOT NULL DEFAULT '{}', attributes_json TEXT NOT NULL DEFAULT '{}',
  schema_version INTEGER NOT NULL,
  PRIMARY KEY (trace_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_trace_session ON trace_events (session_id, turn_index, seq);
CREATE INDEX IF NOT EXISTS idx_trace_kind ON trace_events (session_id, kind, started_at);
CREATE INDEX IF NOT EXISTS idx_trace_event ON trace_events (event_id);
```

- 全量明文入库（用户已批准）；启动与服务运行期间按 `obs_trace_retention_days` 清理过期行。
- 不修改 `run_events`：SSE 仍用旧表；Trace 是独立可升级的存储。

### 4.4 API（`interfaces/api/obs_trace_routes.py`）

| 方法/路径 | 用途 |
|---|---|
| `GET /api/v1/obs/trace/sessions/{session_id}/traces` | 会话的 trace 列表（每轮一条，含状态/耗时/事件数/input_hash） |
| `GET /api/v1/obs/trace/sessions/{session_id}/events` | 平铺事件分页（cursor/limit，preview） |
| `GET /api/v1/obs/trace/traces/{trace_id}` | 单 trace 全量事件树（可按 parent_id 组装） |
| `GET /api/v1/obs/trace/events/{event_id}` | 单事件全量 input/output |

### 4.5 独立配置

`AppConfig` 新增：

```python
obs_trace_enabled: bool = True
obs_trace_retention_days: int = 30
obs_trace_full_payload: bool = True   # False 时回退脱敏摘要（保留契约兼容）
```

关闭后：不采集、Trace API 返回 `6004`；Metrics/Replay 仍可读历史数据。

---

## 五、Metrics 模块

### 5.1 聚合（只读 TraceReader）

`domain/obs/metrics/aggregate.py` 纯函数 + `memory/trace_store.py::aggregate` SQL：

| 维度 | 指标 |
|---|---|
| 全局/会话/Trace | 事件数、失败数、错误率、墙钟时长、p50/p95/p99 |
| kind/name | 各节点耗时分布、失败率、调用次数 |
| model | LLM 调用次数、平均/p95 延迟、token 总量 |
| turn | 每轮 token、动作数、失败动作、六维 score |
| 时间桶 | minute/hour/day 的趋势序列 |

统一输出 `MetricSeries {dimension, key, points[{bucket, count, failed, p50, p95, p99, tokens}], schema_version}`。

### 5.2 阈值规则（纯函数，阈值只在后端）

`domain/obs/metrics/rules.py`：

```python
@dataclass(frozen=True)
class MetricThresholds:
    p95_ms_warn: int; error_rate_warn: float
    token_warn: int; tool_failure_rate_warn: float
    critical_multiplier: float = 2.0

def evaluate(series: Sequence[MetricSeries], thresholds: MetricThresholds) -> list[AlertDraft]
```

规则集：
- `p95_duration`：任一节点 p95 > `obs_metrics_p95_warn_ms`
- `error_rate`：失败事件 / 总事件 > `obs_metrics_error_rate_warn`
- `token_budget`：单 trace token > `obs_metrics_token_warn`
- `tool_failure_rate`：tool.result failed / tool.call > `obs_metrics_tool_failure_warn`
- 严重度：`observed > threshold * critical_multiplier` → `critical`，否则 `warning`。

### 5.3 告警持久化（用户已选）

`memory/obs_schema.py`：

```sql
CREATE TABLE IF NOT EXISTS metrics_alerts (
  alert_id TEXT PRIMARY KEY, rule_id TEXT NOT NULL, severity TEXT NOT NULL,
  status TEXT NOT NULL,                  -- active / resolved
  scope_kind TEXT NOT NULL,              -- session / trace / node
  scope_key TEXT NOT NULL,
  metric TEXT NOT NULL, observed REAL NOT NULL, threshold REAL NOT NULL,
  message TEXT NOT NULL,
  first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
  resolved_at TEXT NOT NULL DEFAULT '',
  cooldown_until TEXT NOT NULL DEFAULT '',
  schema_version INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_active
  ON metrics_alerts (rule_id, scope_kind, scope_key, status);
```

- 评估时机：`TraceListener.on_trace_completed`（Trace 模块只发标准事件）+ `GET /alerts` 查询前补评估。
- 去重/冷却：同 `(rule_id, scope)` 活跃期内只更新 `last_seen_at/observed`；恢复时写 `resolved`，保留历史。
- 不新增通知设施（无 webhook/邮件）。

### 5.4 API（`interfaces/api/obs_metrics_routes.py`）

| 方法/路径 | 用途 |
|---|---|
| `GET /api/v1/obs/metrics/summary?session_id=&trace_id=&from=&to=&group_by=&bucket=` | 多维聚合序列 |
| `GET /api/v1/obs/metrics/alerts?status=&limit=&offset=` | 告警历史（分页） |
| `GET /api/v1/obs/metrics/config` | 生效阈值（只读，前端只展示） |

### 5.5 独立配置

```python
obs_metrics_enabled: bool = True
obs_metrics_p95_warn_ms: int = 5000
obs_metrics_error_rate_warn: float = 0.2
obs_metrics_token_warn: int = 50000
obs_metrics_tool_failure_warn: float = 0.2
obs_metrics_alert_cooldown_s: int = 300
obs_metrics_critical_multiplier: float = 2.0
```

---

## 六、Replay 模块（确定性回放）

### 6.1 回放模型

- 回放单位：一个 `trace_id`（一轮完整执行）。
- **不真实调用 LLM/工具**：`RecordedRunner/Reader/Generator/Decider` 按 `call_key` 从 Trace 中取录制结果；同一 key 多次调用按队列顺序消费。
- 回放执行器：`ReplayExecutionPort` 的适配器 `obs/replay/execution.py`，内部构造一个 **dry-run 的 `ForgeService`**：
  - 注入录制端口、内存版 `SessionStore`/`TurnStore`、`NullProgressSink`、`NullTraceCollector`；
  - 关闭 `trace_enabled/metrics_enabled`，避免递归采集；
  - 不写真实 DB、不发事件、不产生交付副作用；
  - 从 `turn.start.input` 恢复会话快照（原句/project/继承 target/clarifications），调用 `optimize` 复现该轮。
- 校验：
  - 每个节点请求的 `call_key` 必须命中录制结果；未命中 → `missing_record`；
  - 节点输出与录制输出的归一化 JSON 比较 → `match/mismatch`；
  - 最终 snapshot（target/facts/variant/reply/delivery_gate/claim_report/anchor_report）归一化比较。
- 归一化 `domain/obs/replay/normalize.py`：剔除时间戳、随机 ID、进度文本、绝对路径（按用户批准，仅比较业务字段）；排序字典键。

### 6.2 两种运行模式

| 模式 | 输入 | 用途 |
|---|---|---|
| `verify`（单 Trace 自比对） | 1 个 `trace_id` | 代码升级后的回归：重放旧 Trace，节点/最终输出必须与录制一致 |
| `compare`（双 Trace 对比） | 左右 2 个 `trace_id`（要求 `input_hash` 相同） | 多版本（模型/提示词/代码版本）执行结果 diff |

### 6.3 存储 DDL

```sql
CREATE TABLE IF NOT EXISTS replay_runs (
  run_id TEXT PRIMARY KEY, mode TEXT NOT NULL, status TEXT NOT NULL,
  left_trace_id TEXT NOT NULL, right_trace_id TEXT NOT NULL DEFAULT '',
  matched_nodes INTEGER NOT NULL DEFAULT 0, mismatched_nodes INTEGER NOT NULL DEFAULT 0,
  missing_nodes INTEGER NOT NULL DEFAULT 0,
  result_json TEXT NOT NULL DEFAULT '{}', error_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, ended_at TEXT NOT NULL DEFAULT '',
  schema_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS replay_nodes (
  run_id TEXT NOT NULL, seq INTEGER NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
  match INTEGER NOT NULL, expected_json TEXT NOT NULL DEFAULT '{}',
  actual_json TEXT NOT NULL DEFAULT '{}', diff_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (run_id, seq)
);
```

### 6.4 API（`interfaces/api/obs_replay_routes.py`）

| 方法/路径 | 用途 |
|---|---|
| `POST /api/v1/obs/replay/runs` | 创建 verify/compare 任务（返回 202 + run_id） |
| `GET /api/v1/obs/replay/runs/{run_id}` | 任务状态 + 节点对比结果（分页可选） |
| `POST /api/v1/obs/replay/compare` | 双 Trace 对比的便捷入口（等价 create+wait，返回结果） |

### 6.5 自动化回归

- CLI：`scripts/replay_regression.py --trace-id <id> --db <path> [--assert-match]`；不一致退出码 1，可接 CI。
- 测试夹具：`tests/fixtures/traces/*.json`（手工构造的最小 Trace，不依赖真实 LLM）。
- 前端 Replay 页提供「运行回归 / 查看 diff / 导出 JSON」。

### 6.6 独立配置

```python
obs_replay_enabled: bool = True
obs_replay_max_nodes: int = 20000     # 防止病态 Trace 拖死回放
obs_replay_timeout_seconds: float = 120.0
```

---

## 七、模块独立启用 / 配置 / 升级

### 7.1 启用

- `AppConfig` 三个开关：`obs_trace_enabled` / `obs_metrics_enabled` / `obs_replay_enabled`。
- `obs/registry.py` 按开关装配 service、listener、路由依赖；关闭的模块 API 返回 `6004 模块未启用`（新增错误码）。
- 设置中心新增可写的 `observability` 段：

```json
{"trace_enabled": true, "metrics_enabled": true, "replay_enabled": true, "trace_retention_days": 30}
```

`SettingsResponse`/`SettingsUpdate` 增 `observability` 段；`service.update_settings` 写入 app_settings 并 `model_copy(update=...)` 到运行配置（与 process 段同模式）。

### 7.2 升级

- `domain/obs/contract/version.py` 三个 `SCHEMA_VERSION`；写入时落库，读取时按版本映射（旧版本缺失字段补默认）。
- 每模块独立契约测试：`tests/contract/test_trace_contract.py`、`test_metrics_contract.py`、`test_replay_contract.py`。
- 前端每模块独立 Zod schema；只增字段不破坏。

### 7.3 错误码

`6004`：「可观测性模块未启用」。同步：
- `domain/error_codes.py` + `interfaces/api/app.py::_http_status`（映射 404）；
- `frontend/src/schemas/errorCodes.ts` + `zh-CN.json`/`en.json`；
- `scripts/check_architecture.py` 第 7 项自动校验。

---

## 八、前端拆分

目录：

```
frontend/src/features/obs/
├── contract.ts                 # 标准信封、分页、schema_version
├── shared/
│   ├── SessionPicker.tsx       # 会话列表（搜索/项目筛选/分页）
│   ├── VirtualRows.tsx         # 固定行高虚拟列表
│   ├── ExportMenu.tsx          # JSON/CSV 导出
│   ├── format.ts
│   └── obs.module.css
├── trace/
│   ├── TracePanel.tsx          # 会话 → trace 列表 → 事件台账/调用链
│   ├── useTrace.ts
│   ├── TraceLedger.tsx
│   ├── CallTree.tsx
│   ├── TraceInspector.tsx      # 全量 input/output 查看
│   └── trace.module.css
├── metrics/
│   ├── MetricsPanel.tsx        # 维度/时间桶选择 + KPI + 趋势 + 告警历史
│   ├── useMetrics.ts
│   ├── MetricCharts.tsx        # SVG 折线/柱状/分布
│   ├── AlertsTable.tsx
│   └── metrics.module.css
└── replay/
    ├── ReplayPanel.tsx         # Trace 选择 → verify/compare → 节点结果/diff
    ├── useReplay.ts
    ├── ReplayTimeline.tsx      # 复用现有时间轴交互
    ├── ReplayControls.tsx
    ├── ReplayDiff.tsx
    └── replay.module.css
```

- 设置中心 `ObservabilityPanel.tsx` 只做外壳：读取 `settings.observability` 决定显示哪些标签（Trace / Metrics / Replay），三者互不 import。
- 现有 `components/settings/observability/*` 的台账/时间轴组件按职责迁移：日志台账 → `trace/`，时间轴/播放 → `replay/`，图表/指标 → `metrics/`。
- Trace 页默认展示 preview；点击事件后调 `GET /obs/trace/events/{id}` 看全量（避免列表一次传大 payload）。
- Replay 页显示每个节点的 `match/mismatch/missing`、expected/actual diff、最终快照 diff；支持「导出 JSON」与「复制失败节点」。
- Metrics 页的阈值只从 `GET /obs/metrics/config` 读取并展示，前端不出现阈值常量（MUST-08）。

---

## 九、破坏性变更与迁移

| 变更 | 处理 |
|---|---|
| 删除 `domain/observability/` 与 `interfaces/api/observability_routes.py` | 由三模块替代；旧 `GET /sessions/{id}/observability` 下线（BREAKING） |
| `openapi.json` 路径变化 | 重新导出；`tests/api/test_openapi.py` 路径/操作数从 24/27 改为 **33/36** |
| 前端旧 `schemas/observability.ts`、`useObservability.ts` | 拆成三模块的 schema/hook；旧组件迁移或删除 |
| 旧会话无 Trace | Trace 页显示「该会话没有 Trace（旧数据未采集）」，不伪造；不做回填 |
| MUST-19 | `AGENTS.md` 增补例外：Trace 存储可保存完整输入/输出（本地 SQLite），但密钥字段仍掩码、禁止写入日志、禁止自动外传；保留期由配置控制 |
| `run_events` | 保留给 SSE，不改表；Trace 独立存储（数据有重复，换取模块独立升级） |

---

## 十、测试与验证

### 10.1 后端

- `tests/domain/obs/test_trace_tree.py`：调用链树、分页、preview。
- `tests/domain/obs/test_metrics_aggregate.py`：分组/分桶/分位数/空数据。
- `tests/domain/obs/test_metrics_rules.py`：各规则触发、严重度、冷却/恢复。
- `tests/domain/obs/test_replay_engine.py`：call_key 命中、缺失记录、节点 mismatch、最终快照 diff、normalize 去噪。
- `tests/memory/test_trace_store.py`：写入/读取/按 kind/时间查询/聚合/保留期清理。
- `tests/api/test_obs_trace_api.py`、`test_obs_metrics_api.py`、`test_obs_replay_api.py`：契约、分页、6004、权限 6003。
- `tests/integration/test_trace_collection.py`：用 Fake 端口跑一轮 `optimize`，断言 turn/action/llm/tool/file 事件齐全、seq 连续、父链正确。
- `tests/integration/test_replay_regression.py`：录制一轮（Fake LLM/工具）→ 改动无害代码 → 回放必须 match；改动输出 → 必须 mismatch。
- `tests/api/test_openapi.py`：33 路径 / 36 操作 + 新模型存在。
- `uv run pytest tests -q`、`ruff check`、`ruff format --check`、`mypy src`、`python scripts/check_architecture.py`。

### 10.2 前端

- 每模块独立测试：`TracePanel.test.tsx`、`MetricsPanel.test.tsx`、`ReplayPanel.test.tsx`；
- 迁移现有 `logModel`/`exportData`/`ReplayTimeline` 测试到对应 feature 目录；
- `ObservabilityPanel.test.tsx`：按 settings 开关隐藏模块；模块间切换不共享内部状态；
- `pnpm typecheck`、`pnpm lint`、`pnpm test`、`pnpm check:css`、`pnpm format:check`、`pnpm build`。

### 10.3 手工验收

1. 启动服务，跑一轮真实任务：Trace 页能看到 turn/action/llm/tool/file 全链路，点开事件可见完整输入输出。
2. Metrics 页按 kind/model/turn 聚合，阈值告警出现在告警历史；重启后历史仍在。
3. Replay 页对同一 Trace 执行 verify，全部节点 match；人为改一个模板输出后必须 mismatch 并给出 diff。
4. 两个同输入、不同模型版本的 Trace 执行 compare，diff 可读。
5. 关闭 trace / metrics / replay 开关后，对应标签消失、直接调 API 返回 6004，其余模块不受影响。
6. 旧会话在 Trace 页显示「无 Trace 数据」，Metrics/Replay 不崩溃。

---

## 十一、实施顺序

1. 共享契约 + `obs_schema` + 三个 store（纯模型、DDL、读写/聚合）。
2. Trace 采集：collector + traced 包装器 + `ForgeService` 接线 + 集成测试。
3. Trace API + 前端 Trace 页（从现有日志台账迁移）。
4. Metrics：聚合 + 规则 + 告警持久化 + listener + API + 前端 Metrics 页。
5. Replay：playback + dry-run executor + 录制端口 + verify/compare + CLI + 前端 Replay 页。
6. 设置开关、6004、openapi/契约、删除旧实现。
7. 全量门禁 + 手工验收 + 文档（AGENTS.md MUST-19 例外、架构文档目录树）。

---

## 十二、假设与决策

| # | 决策 | 依据 |
|---|---|---|
| D1 | Replay = 确定性回放，不真实调用 LLM/工具 | 你已选择；无副作用、可回归 |
| D2 | Trace 全量明文入库 | 你已选择；MUST-19 增补本地例外，密钥仍掩码 |
| D3 | 告警持久化历史，不做外部推送 | 你已选择 |
| D4 | Trace 存储与 `run_events` 分离 | 独立升级/保留策略；SSE 不受影响 |
| D5 | Trace 写失败 fail-open（标记 partial） | 可观测性不得阻断业务；UI 如实披露 |
| D6 | 旧会话不回填 Trace | 旧实现未采集完整输入输出，回填会伪造完整性 |
| D7 | 模块开关可运行时修改（settings） | 满足独立启用/配置 |
| D8 | Trace 列表只传 preview，详情单独取 | 全量明文可能很大，避免列表阻塞 |
| D9 | 事件模型 parent_id 构成调用链树 | 对齐 DeerFlow 节点化/图执行思路 |
| D10 | Replay 单 Trace 自比对 + 双 Trace 版本对比 | 分别覆盖回归与多版本场景 |

---

## 十三、风险与应对

| 风险 | 应对 |
|---|---|
| 全量明文导致库膨胀 | 保留期（默认 30 天）+ 按会话/时间索引 + 运维脚本 `scripts/cleanup_traces.py` |
| Trace 写入影响主链延迟 | 有界队列 + 批量写 + 失败降级；压测单轮写入 P95 |
| dry-run 复用了生产 `ForgeService`，未来改动可能破坏回放 | `ReplayExecutionPort` 适配层 + 回归夹具；服务构造参数 `replay_mode` 显式化 |
| 录制输出缺失 | 回放任务标 `diverged/missing_record`，给出缺失 call_key 与节点位置 |
| 模块开关与前端不同步 | 设置响应下发 flags；前端隐藏 + 后端 6004 双保险 |
| MUST-19 例外被误用 | 仅 Trace 存储与用户主动导出；密钥字段强制掩码；不写日志/不发外部 |

---

## 十四、参考

- DeerFlow 官网架构说明（Coordinator → Planner → Research Team → Reporter，LangGraph 模块化工作流）：<https://deerflow.tech/workspace/chats/fe3f7974-1bcb-4a01-a950-79673baafefd>
- DeerFlow 源码流程解读（planner/research_team/reporter 节点与状态流转）：<https://juejin.cn/post/7541935177010954280>
- DeerFlow Gitee 镜像架构说明：<https://gitee.com/fastdgiot/deer-flow>
