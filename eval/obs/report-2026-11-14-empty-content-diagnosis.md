# 可观测性四模块「无内容输出」专项排查与测试报告（2026-11-14）

## 一、结论摘要

**不是采集或接口整体失效。** 真实数据库中的最后一次会话产生于 2026-11-12，早于可观测性数据接入；四个面板默认读取「历史列表第一条（最新会话）」，因此全部显示空态。补跑一次真实会话后，四模块全部正常出数，且跨模块关联键一致。

排查中另发现并修复 2 个真实缺陷：

| 编号 | 级别 | 问题 | 状态 |
|---|---|---|---|
| F-01 | P0 | Replay 的 Verify/Compare（以及撤销、模型切换）请求体被 `JSON.stringify` 二次编码，后端 422，前端显示 `status: failed · ApiError: 响应外壳不符合契约` | 已修复 |
| F-02 | P1 | 旧入口 `/optimize` 的 Session Log 写入在 API 单测中触发真实 runtime，把测试事件写进用户真实库（`s1` / `s-stream` / 随机 UUID） | 已修复（配置守卫） |
| F-03 | P2 | 四面板默认选择「最新会话」，若该会话无观测数据则整体空白，缺少「该会话无数据」的引导 | 建议项 |

验证用真实会话：`36167b7a2d904a07b25e93cf6c051929`（项目 `eval/recall/mock-react-admin`）。

## 二、环境与初始状态

| 项 | 值 |
|---|---|
| 后端 | `http://127.0.0.1:8000`（进程启动于 2026-11-14 13:07，已含最新代码） |
| 前端 | `http://127.0.0.1:5173`（Vite 代理 `/api` → 8000） |
| 真实库 | `~/.devprompt-ai/devprompt.db` |
| 可观测性开关 | settings.json `process` 段无 `obs_*` 键 → 全部按默认值 `true` |
| 路由与模块 | `/api/v1/obs/trace|metrics|replay` 均已注册；`obs_modules()` 懒加载正常 |

初始库内计数（排查前）：

| 表 | 行数 | 说明 |
|---|---|---|
| `forge_sessions` | 74 | 最新会话 `2026-11-12T11:53:18Z` |
| `run_events` | 138 | 仅属于 `s1` / `s-stream` / 测试 UUID，真实会话 0 条 |
| `trace_events` | **0** | 全部真实会话均无 Trace 数据 |
| `metrics_alerts` | **0** | 无 Trace 可评估 |
| `replay_runs` / `replay_nodes` | **0** / **0** | 无可回放 Trace |

接口实测：对最新的旧会话查询
`/events`、`/obs/trace/sessions/{id}/traces`、`/obs/trace/sessions/{id}/events`、
`/obs/metrics/summary` 均返回 **HTTP 200 + 空数组**；`/obs/replay/runs/none` 返回 6003。
说明服务端与模块开关正常，问题是**该会话确实没有数据**。

## 三、根因定位

1. **历史数据缺失（主因）**：74 个真实会话都在可观测性接线之前/旧入口回退路径上产生。
   - Trace/Metrics/Replay 依赖 `trace_events`，旧会话从未写入；
   - Session Log 依赖 `run_events`，旧入口 `/optimize`、`/optimize/stream` 在修复前不写事件；
   - 观测数据不做历史追溯补齐，因此旧会话永远是空。
2. **默认会话选择**：`SessionLogPanel` / `TracePanel` / `MetricsPanel` / `ReplayPanel` 都以
   `GET /history?limit=50` 的 `items[0]`（按 `updated_at` 最新）作为默认会话。打开的正是
   无数据的旧会话，于是四个标签同时空白。
3. **Replay 前端契约缺陷（真实 bug）**：`frontend/src/api/endpoints.ts` 中
   `createObsReplay` / `compareObsTraces` / `rollbackSession` / `setSessionModel` 把对象先
   `JSON.stringify`，而 `client.request()` 内部又 `JSON.stringify(body)` 一次，实际发出的是
   JSON **字符串**。FastAPI 收到字符串报 `model_attributes_type` → 422 → 前端契约错误。
   证据：Network 面板 `POST /api/v1/obs/replay/runs [422]`，请求体为
   `"{\"mode\":\"verify\",\"left_trace_id\":\"...\"}"`。
4. **测试隔离缺陷**：`routes._event_log` 通过 `runtime_routes._bundle()` 初始化真实 runtime；
   API 单测的 `get_service` 只 patch 了 `routes.get_service`，`runtime_routes` 仍绑定原函数，
   导致单测把 `s1` / `s-stream` 等事件写进用户真实库。已在 `_event_log` 增加
   `service.config` 守卫，Fake service 直接跳过。

## 四、专项测试用例与结果

### 4.1 Session Log

| 用例 | 步骤 | 预期 | 实际 | 结果 |
|---|---|---|---|---|
| SL-01 正常采集 | `POST /runs`（新 UUID）→ 订阅 `/sessions/{id}/stream` | 收到 `run.started → thought/action → snapshot → stop` | 20 条事件，状态 `done/DONE` | PASS |
| SL-02 存储查询 | `GET /events?session_id=36167...&limit=100` | 按 seq 升序、无重复 | 20 条，seq 1–20，类型 6 种 | PASS |
| SL-03 页面渲染 | 设置 → 可观测性 → Session Log | 显示事件计数与列表 | `events: 20`，可见 `run.started/thought/action` 行 | PASS |
| SL-04 边界（旧会话） | 选择 `2026-11-12` 旧会话 | 返回空且不报错，UI 显示空态 | `200 + []` | PASS |
| SL-05 边界（写失败） | 既有 AB-06 回归 | 业务成功、fail-open | `snapshot.status=done` | PASS |

### 4.2 Trace

| 用例 | 步骤 | 预期 | 实际 | 结果 |
|---|---|---|---|---|
| TR-01 采集 | 新会话运行后查 `/obs/trace/sessions/{id}/traces` | 1 条 trace，含 start/end | 1 条：`36167...:0:diag-35a` | PASS |
| TR-02 数据完整性 | 查 trace 事件并核对 DB | seq 连续、种类齐全 | 59 条，seq 1–59 连续，0 失败，`turn.start/end` 各 1 | PASS |
| TR-03 关键节点 | 过滤 `llm.response` | 存在且 token > 0 | `llm_tokens=[14187]` | PASS |
| TR-04 页面渲染 | 可观测性 → Trace | 显示 trace 与事件台账 | `traces: 1 · events: 59`，含 llm/tool/file 等节点 | PASS |
| TR-05 边界（旧会话） | 旧会话查 traces | 空数组 | `200 + []` | PASS |
| TR-06 边界（模块关闭） | 既有 TR-05 用例 | 6004 | 6004 | PASS |

### 4.3 Metrics

| 用例 | 步骤 | 预期 | 实际 | 结果 |
|---|---|---|---|---|
| MT-01 聚合 | `GET /obs/metrics/summary?session_id=...&group_by=kind` | 按 kind 出序列 | 12 个 kind，计数合计 59（与 trace 事件数一致） | PASS |
| MT-02 告警 | `GET /obs/metrics/alerts` | 超阈值生成告警 | `p95_duration · critical · active`（scope=trace） | PASS |
| MT-03 页面渲染 | 可观测性 → Metrics | 展示阈值、聚合条、告警 | P95 5000ms 等配置 + `action.end/decision.*/file.read` 条形图 | PASS |
| MT-04 边界（旧会话） | 旧会话 summary | 空数组 | `200 + []` | PASS |
| MT-05 边界（模块关闭） | 既有 MT-06 | 6004 | 6004 | PASS |

### 4.4 Replay

| 用例 | 步骤 | 预期 | 实际 | 结果 |
|---|---|---|---|---|
| RP-01 API Verify | `POST /obs/replay/runs {mode:verify}` + 轮询 | matched | `matched`，38 节点，mismatch 0，missing 0 | PASS |
| RP-02 页面 Verify | 可观测性 → Replay → 点击 Verify | 时间线与 matched 状态 | **修复前**：422 + `ApiError: 响应外壳不符合契约`；**修复后**：`status: matched · mismatch: 0` | PASS（修复后） |
| RP-03 未知 run | `GET /obs/replay/runs/none` | 6003 | 6003 | PASS |
| RP-04 边界（无 Trace） | 旧会话 | 无可选 trace，不发起请求 | 下拉为空，Verify 无输入 | PASS |
| RP-05 Compare | `POST /obs/replay/compare` | 返回节点与 final | 修复后正常（同一编码缺陷已修） | PASS |

### 4.5 跨模块一致性

| 用例 | 断言 | 实际 | 结果 |
|---|---|---|---|
| XM-01 关联键 | `run.started.request_id` == Trace `run_id` == `turn.start.attributes.run_id` | 均为 `diag-35aadc6d` | PASS |
| XM-02 计数一致 | Metrics kind 计数合计 == Trace 事件数 | 59 == 59 | PASS |
| XM-03 回放归属 | `left_trace_id` 属于同一会话、节点子集 | 同名 trace，38 节点 matched | PASS |
| XM-04 完整性 | Trace seq 连续、start/end 各 1、无失败 | 59/1/1/0 | PASS |
| XM-05 Session Log seq | 1–20 连续无重复 | 通过 | PASS |

## 五、修复内容

1. **F-01 请求体二次编码**（`frontend/src/api/endpoints.ts`）
   - `createObsReplay`、`compareObsTraces`、`rollbackSession`、`setSessionModel` 改为传对象，
     由 `request()` 统一编码；
   - 新增回归测试 `frontend/src/api/endpoints.test.ts`：
     `Replay/模型切换请求体只编码一次`。
2. **F-02 测试隔离**（`src/devprompt_ai/interfaces/api/routes.py`）
   - `_event_log(service, ...)` 增加 `service.config` 守卫；Fake service 不触发真实 runtime；
   - 对应 API 单测显式注入 `config`，保持 D-05 行为覆盖。
3. **F-03 建议（未改代码）**
   - 四面板默认选择「最近一条存在观测数据的会话」，或在空态明确提示
     「该会话无观测数据，请先执行一次运行」；
   - 启动日志打印 `db_path + obs_* 开关`，便于区分「无数据」与「未启用」。

## 六、复现步骤（可追溯）

```powershell
# 1) 初始状态核对（空数据根因）
python - <<'PY'
import sqlite3, pathlib
db = pathlib.Path.home()/".devprompt-ai"/"devprompt.db"
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
for t in ("forge_sessions","run_events","trace_events","metrics_alerts","replay_runs"):
    print(t, c.execute(f"select count(*) from {t}").fetchone()[0])
PY

# 2) 跑一次真实会话（新 UUID）
#    POST /api/v1/runs {session_id, project, sentence} → 订阅 /sessions/{id}/stream?since=0

# 3) 四模块数据核对
#    GET /api/v1/events?session_id=<sid>
#    GET /api/v1/obs/trace/sessions/<sid>/traces
#    GET /api/v1/obs/trace/sessions/<sid>/events?limit=500
#    GET /api/v1/obs/metrics/summary?session_id=<sid>&group_by=kind
#    GET /api/v1/obs/metrics/alerts
#    POST /api/v1/obs/replay/runs {"mode":"verify","left_trace_id":"<trace>"}

# 4) 页面验证
#    http://127.0.0.1:5173 → 设置 → 可观测性 → 依次切换四个标签
```

测试证据（2026-11-14 本轮）：

- Session Log：20 条，seq 1–20；
- Trace：1 条 trace、59 事件、seq 1–59、`llm.response.tokens=14187`；
- Metrics：12 个聚合序列（合计 59）+ 1 条 `p95_duration/critical`；
- Replay：`matched`、38 节点、mismatch 0；
- 关联键：`run.started.request_id = turn.start.run_id = diag-35aadc6d`。

## 七、回归门禁

| 检查 | 结果 |
|---|---|
| 后端全量 pytest | 1389 passed, 14 skipped |
| 前端 typecheck / eslint / vitest | 通过；46 文件 330 用例通过 |
| ruff check / format | 通过 |
| mypy src | 199 文件无问题 |
| 架构约束检查 | 通过 |
| prettier --check | 通过 |

## 八、遗留与建议

1. **测试残留数据**：用户库 `run_events` 中残留 6 个无对应 `forge_sessions` 的测试会话
   （共 138 条：`s1` 18、`s-stream` 50、`247cf2c2…` 17、`9520703c…` 18、`9dc6ab4a…` 17、
   `ca5de1a3…` 18）。UI 不可见，建议确认后清理：
   ```sql
   DELETE FROM run_events WHERE session_id IN (
     's1', 's-stream',
     '247cf2c242364eb89078aec71902faa1',
     '9520703c7cc64bd584db90ea3e910f1c',
     '9dc6ab4a0ad845549151ef1202539bcf',
     'ca5de1a39e4a4389a0516b73cd59a58c'
   );
   ```
2. **历史会话不会补齐**：Trace/Metrics/Replay 只覆盖接入后的运行；旧会话只能看到空态。
3. **页面默认会话选择**：建议按 F-03 优化，减少「明明有数据却打开旧会话」的误解。
