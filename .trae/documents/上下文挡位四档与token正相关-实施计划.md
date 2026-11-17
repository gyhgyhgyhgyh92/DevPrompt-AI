# 上下文挡位四档化与 token 正相关 · 实施计划

> 日期：2026-11-10  
> 状态：待批准  
> 任务类型：配置策略调整 + 预算联动 + 计量验证  
> 用户裁决：
> 1. 档位为 **300K / 600K / 1M + 模型标称值动态补位**，最多 4 档；
> 2. 不足 4 档时用 **128K** 补最低档；
> 3. 挡位仍**按模型独立选择**，不做全局单开关；
> 4. 上下文预算随挡位缩放：`clamp(档位 × 10%, 30K, 160K)`。

---

## 一、摘要

当前窗口档位由 `window_tiers()` 用「厂商档位 ∪ 128K 起的 2 的幂阶梯」生成，结果是 128K/256K/512K/1M 这类曲线，与产品规划的 300K/600K/1M 不一致；同时上下文装配预算固定为 `max_state_tokens=30000`，所以“窗口调大”并不会让 token 消耗单调上升。

本计划做三件事：

1. 把窗口档位改为**统一四档策略**：300K / 600K / 1M + 标称值，必要时用 128K 补位，最多 4 档；
2. 让上下文装配总预算随档位缩放（300K→30K、600K→60K、1M→100K、2M→160K），使窗口越大、可保留的历史越多、token 消耗越高；
3. 补齐 token 计量的兜底与对账测试，保证 `prompt + completion = total` 口径稳定、无负数/空值偏差。

不引入任何 SDK 依赖，不改供应商协议。

---

## 二、四个 SDK 的调研结论（与本次档位策略相关）

| SDK | 上下文窗口控制 | 对本次的启示 |
|---|---|---|
| **Codex SDK**（`@openai/codex-sdk`） | Codex config `model_context_window`，单值；超出自动截断历史；无“四档”概念 | 窗口是本地预算，不是请求参数；超限应压缩历史 |
| **Trae** | IDE 高级设置里的“Context Window (Token)”可手填/选预设；Max 模式 200K→1M | 预设档位是产品配置，不是厂商协议 |
| **CodeBuddy SDK** | 文档以 `maxInputTokens` / auto-compact window 表达；无统一窗口请求字段 | 大窗口需要配套的自动压缩阈值 |
| **Qoder SDK** | CLI `resolveModel.parameters.contextWindow`；Cloud `model.context_window` 来自模型 `available_context_windows` | 档位必须来自模型可用集合，且按请求/模型独立 |

结论：四者都没有可直接复用的“四档 300K/600K/1M”实现；本项目按控制面语义自建统一档位策略。

---

## 三、现状分析（代码事实）

| 位置 | 事实 |
|---|---|
| `domain/model_spec.py:111-126` | `window_tiers(window, vendor_tiers)` = 厂商档位 ∪ 128K 起的 2 的幂阶梯，最多可能 5 档（如 OpenAI 272K → 128K/131K/262K/272K） |
| `domain/model_spec.py:624-633` | `ModelMeta.to_dict()` 用 `window_tiers(window, vendor_tiers)` 投影模型级档位 |
| `domain/model_spec.py:768-805` | `providers_projection()` 用 `window_tiers(spec.max_context_length, spec.context_window_tiers)` 投影厂商级档位 |
| `domain/model_catalog/catalog.py:71-79` | `clean_tiers()` 只做去重/升序/≤窗口，不限制档位数量 |
| `domain/model_catalog/catalog.py:200-221` | `effective_context_window()` 用 `window_tiers()` 校验选中档位；非法则回落标称值 |
| `config.py:142` | `max_state_tokens=30000`，当前作为上下文装配的固定总预算 |
| `service.py:2890` | `ContextBudget(total=self._cfg.max_state_tokens)`，不随窗口变化 |
| `service.py:1547` | 六维感知的 `context_window` 也用 `max_state_tokens` |
| `decision/fallback.py:99/129/195/241` | `_fit_state(..., self._cfg.max_state_tokens)` 四处固定截断 |
| `harness/llm.py:213-227` | `_record_usage()` 只取 `usage.total_tokens`；缺失时记 0 |
| `service.py:1562-1587` | `_account_llm_usage()` 累加 total/prompt/completion/cached；未做缺失兜底与负数保护 |
| `frontend ModelPicker` | 档位完全由后端 `context_window_tiers` 下发；前端只渲染，无阈值逻辑 |
| 现有数据 | 旧档位可能是 131072/262144/524288/1048576；新策略下 262144/524288 不再合法 |

---

## 四、目标设计（决策完成）

### 4.1 四档算法

在 `domain/model_spec.py` 增加常量：

```python
CONTEXT_TIER_PRESETS = (300_000, 600_000, 1_048_576)  # 300K / 600K / 1M
CONTEXT_TIER_LOW = 131_072                            # 128K，补位用
MAX_CONTEXT_TIERS = 4
```

`window_tiers(window)` 改为：

```python
def window_tiers(window: int | None) -> tuple[int, ...]:
    if window is None or window <= 0:
        return ()
    tiers = {tier for tier in CONTEXT_TIER_PRESETS if tier <= window}
    tiers.add(window)                       # 标称值动态补位
    if len(tiers) < MAX_CONTEXT_TIERS and CONTEXT_TIER_LOW <= window:
        tiers.add(CONTEXT_TIER_LOW)         # 不足 4 档用 128K 补最低档
    ordered = sorted(tiers)
    if len(ordered) > MAX_CONTEXT_TIERS:
        ordered = ordered[-MAX_CONTEXT_TIERS:]  # 超出时丢掉最低档
    return tuple(ordered)
```

**示例**：

| 模型标称窗口 | 档位 |
|---:|---|
| 128K | 128K（单档，UI 禁用） |
| 200K | 128K / 200K |
| 272K | 128K / 272K |
| 300K | 128K / 300K |
| 500K | 128K / 300K / 500K |
| 600K | 128K / 300K / 600K |
| 1M | 128K / 300K / 600K / 1M |
| 1.5M | 300K / 600K / 1M / 1.5M |
| 2M | 300K / 600K / 1M / 2M |

> 1M 模型为 128K/300K/600K/1M 四档；超过 1M 的模型保留 300K/600K/1M/标称值，不再补 128K（保持最多 4 档）。

### 4.2 旧档位迁移

新增纯函数：

```python
def nearest_context_tier(value: int, nominal: int | None) -> int:
    """把旧档位归一到新档位集：取绝对差最小者，平局取较小值；
    标称窗口未知时原样返回。"""
```

在 `domain/model_migration.normalize_entry()` 里对 `max_context_length` 做归一：

- 262144 → 300000
- 524288 → 600000
- 131072 / 128000 → 131072
- 1048576 → 1048576
- 200000 → 200000（标称值补位）
- 标称窗口未知 → 保留原值（没有合法集合，无法归一）

读时与写时都经过 `normalize_registry()`，因此旧设置首次读取即归一，下一次保存落盘。

### 4.3 上下文预算随档位缩放

在 `domain/context/budget.py` 增加纯函数：

```python
STATE_BUDGET_RATIO = 0.10
STATE_BUDGET_CAP = 160_000

def state_budget_for_window(window: int, *, floor: int = 30_000) -> int:
    return max(floor, min(int(window * STATE_BUDGET_RATIO), STATE_BUDGET_CAP))
```

| 窗口 | 状态预算 |
|---:|---:|
| 128K / 200K / 272K / 300K | 30K（floor） |
| 500K | 50K |
| 600K | 60K |
| 1M | 100K |
| 2M | 160K |

`max_state_tokens` 语义从“固定总预算”改为**预算下限**；`AppConfig.runtime_state_budget()` 返回上述计算值。

### 4.4 token 正相关的确定性来源

同一段长历史，在不同档位下：

```
档位 300K → state_budget 30K → 只保留 recent/digest/older 的 30K 版本
档位 600K → state_budget 60K → 保留更多历史
档位 1M   → state_budget 100K → 保留最多历史
```

因此 `history_block` 的估算 token 数单调不减；真实请求的 `usage.prompt_tokens` 也应随档位上升（供应商缓存只影响计费折扣，不影响 prompt token 口径）。

---

## 五、实现改动

### 5.1 `src/devprompt_ai/domain/model_spec.py`

1. 新增 `CONTEXT_TIER_PRESETS` / `CONTEXT_TIER_LOW` / `MAX_CONTEXT_TIERS`。
2. `window_tiers(window)` 改为 §4.1 算法；**移除 `vendor_tiers` 参数**，不再使用厂商档位参与 UI 档位生成。
3. 新增 `nearest_context_tier(value, nominal)`。
4. `ModelMeta.to_dict(window)` 与 `providers_projection()` 改调新函数。
5. `ProviderSpec.context_window_tiers` / `ModelMeta.context_window_tiers` 保留为厂商元数据，但在 docstring 中注明“不再参与统一档位生成”。

### 5.2 `src/devprompt_ai/domain/model_catalog/catalog.py`

1. `static_catalog` / `merge_catalog` / `effective_context_window` 全部改用 `window_tiers(window)`。
2. `clean_tiers` 仍保留去重/≤窗口；不再接收远端档位作为 UI 档位来源。
3. 更新模块 docstring：档位是“系统预算档位”，不是厂商规格。

### 5.3 `src/devprompt_ai/domain/model_migration.py`

1. `normalize_entry()` 对 `max_context_length` 调 `nearest_context_tier(window, capabilities.max_context_length)`。
2. 标称未知或 window 非正整数时保持原逻辑（None/原值），不抛异常。

### 5.4 `src/devprompt_ai/domain/context/budget.py`

1. 新增 `state_budget_for_window()` 与两个常量。
2. 更新模块 docstring：`max_state_tokens` 是下限，不是固定总预算。

### 5.5 `src/devprompt_ai/config.py`

1. 新增：
   ```python
   def runtime_state_budget(self) -> int:
       return state_budget_for_window(self.runtime_window(), floor=self.max_state_tokens)
   ```
2. `max_state_tokens` 注释改为“状态预算下限（默认 30K，随档位放大，上限 160K）”。

### 5.6 `src/devprompt_ai/common/cost.py` 与 token 聚合

当前 `add_llm_tokens/take_llm_tokens` 只累计 total，prompt/completion 只在生成/回答后取 `last_usage()`，
探针/排序/打分调用产生的 prompt/completion **没有进入账本**。本次改为按请求聚合：

```python
@dataclass(frozen=True)
class Usage:
    total: int = 0
    prompt: int = 0
    completion: int = 0
    cached: int | None = None

def add_llm_usage(total, prompt, completion, cached) -> None: ...
def take_llm_usage() -> Usage: ...   # 取用即清零
```

- 保留 `add_llm_tokens/take_llm_tokens` 作为 total 兼容包装（若有旧调用）；
- `harness.llm._record_usage` 每次调用都写入聚合器；
- `service._account_usage` 取聚合值，一次性更新 `cost_llm_tokens` / `cost_tokens` /
  `cost_prompt_tokens` / `cost_completion_tokens` / `cost_cached_tokens`；
- 删除 `_act_generate` / `_act_reply` 中单独调用 `_account_llm_usage(last_usage())` 的路径，
  避免与聚合器重复计数；`_record_sensorium` 前先调 `_account_usage`，保证六维压力读到最新成本；
- `_finish_turn` 与 `_snapshot` 的 `_account_usage` 因取用即清零，天然幂等。

### 5.7 `src/devprompt_ai/service.py`

1. `_assemble_context`：`ContextBudget(total=self._cfg.runtime_state_budget())`。
2. `_record_sensorium`：`context_window=self._cfg.runtime_state_budget()`，并在读取成本前调 `_account_usage`。
3. `_account_usage`：按 §5.6 聚合更新全部 token 字段。
4. 新增事件 `context.tier_changed`（若会话轮次间档位变化，记录 from/to/window/state_budget；不含原句）：
   在 `optimize` 重建 `session.data` 前捕获上一轮的 `context_window`/`state_budget`，与 `runtime_window()`/
   `runtime_state_budget()` 比较后 emit，并登记到 `observability/logging.py::EVENT_NAMES`。
5. `_snapshot` 的 `CostBreakdown.total_tokens` 继续等于累计 `llm_tokens`；新增对账断言（测试层）。

### 5.8 `src/devprompt_ai/decision/fallback.py`

四处 `_fit_state(..., self._cfg.max_state_tokens)` 改为 `self._cfg.runtime_state_budget()`；保证决策层截断口径与上下文装配一致。

**测试配套**：`tests/decision/test_fallback.py` 现有 `max_state_tokens=10` 的截断用例需同时设置
`max_context_length=100`（runtime window 100 → state_budget=10），否则默认 1M 窗口会把预算抬到 100K，
原断言不再成立。这是语义从“固定总预算”改为“下限”的预期影响。

### 5.9 `src/devprompt_ai/harness/llm.py`

`_record_usage()`：

- **dict 形态的 usage 也必须取到 total**：当前 `getattr(usage, "total_tokens", 0)` 对原生适配器返回的 dict 恒为 0；
  改为复用 `_usage_int(usage, "total_tokens")`；
- `total_tokens` 缺失/为 0 且 prompt/completion 有值时，取两者之和；
- 所有 token 值 `max(0, int())`，避免供应商返回负数或 None 造成统计偏差；
- 每次调用都写入 `add_llm_usage(total, prompt, completion, cached)`；
- `_last_usage` 字段保持 total/prompt/completion/cached 不变（探针脚本继续使用）。

### 5.10 前端

档位由后端下发，前端逻辑无需改动；只更新测试夹具：

- `ModelPicker.test.tsx` DeepSeek 档位改为 `[131072, 300000, 600000, 1048576]`，断言 `131K/300K/600K/1M`；
- `ConsoleInput.test.tsx` 点击 `300K`，断言 `max_context_length:300000`；
- `ModelServicePanel.test.tsx` 夹具同步新档位；
- 保留 `none` 过滤、关闭写空串等既有行为。

### 5.11 文档

1. `DevPrompt-AI-功能清单.md`：
   - `MAX_STATE_TOKENS` 行改为“状态预算下限（30K，随档位放大，上限 160K）”；
   - F-903 验收改为“各档位下历史承载量随 state_budget 单调增加，current 层永不裁”；
   - 附录 state 上限说明同步。
2. `DevPrompt-AI-项目架构文档.md` §1.6 的 `MAX_STATE_TOKENS` 说明同步。
3. `DevPrompt-AI-技术栈文档.md` 无需新增依赖，不改。

---

## 六、参数校验与异常边界

| 场景 | 行为 |
|---|---|
| 旧档位 262144/524288 | `normalize_entry` 归一到 300000/600000；读时生效、写时落盘 |
| 选中值不在新档位集 | `effective_context_window` 回落标称值；写入校验拒绝新非法值 |
| 选中值 > 标称窗口 | 拒绝/回落，绝不出现“选 1M 实际 200K” |
| 标称窗口未知 | 档位为空，UI 不渲染上下文段；保留原窗口值不归一 |
| 档位切换 | `PUT /settings { models }` 后当前激活条目立即镜像进 `AppConfig`，下一轮生效；无重启 |
| state_budget 计算 | `max(floor, min(10% × window, 160K))`；小窗口不低于 floor，大窗口不超过 cap |
| token 负数/None | 统计层 `max(0, int())`；缺失 total 用 prompt+completion 兜底 |
| total 与 prompt+completion 不一致 | 以供应商 `total_tokens` 为准；测试记录偏差，不静默改写 |
| current 层超预算 | 不硬截断；记录 `truncated_layers=current`，请求预算不足时按既有 3003/压缩重试路径处理 |

---

## 七、测试与验证

### 7.1 单元测试

**档位算法** `tests/domain/test_model_spec.py`：
- 128K/200K/272K/300K/500K/600K/1M/1.5M/2M 的档位表；
- 最多 4 档、升序、去重、≤标称；
- 超过 1M 时丢最低档，保留标称值。

**迁移** `tests/domain/test_model_migration.py`：
- 262144→300000、524288→600000、128000→131072；
- 标称未知保持不变；
- 归一幂等。

**目录/回落** `tests/domain/test_model_catalog.py`：
- `static_catalog` DeepSeek 档位改为 128K/300K/600K/1M；
- `merge_catalog` 不再采用远端 tiers（改用统一策略）；
- `effective_context_window` 选中 262144 时回落标称 1M；选中 300000 时生效；
- 现有 64K/200K 档位断言同步更新。

**预算** `tests/domain/context/test_budget.py`：
- `state_budget_for_window` 各档位值；
- floor/cap 边界（64K、160K、2M、负数/0）。

**上下文承载** `tests/domain/context/test_build_context.py`：
- 同一段长历史（≥2000 轮）在 30K/60K/100K 预算下，`estimate_tokens(history_block)` 单调不减；
- `current` 层 token 不随预算变化；
- 不超过预算上限。

**token 计量**：
- `tests/common/test_cost.py`（或现有等价文件）：两次 `add_llm_usage` 后 `take_llm_usage` 的 total/prompt/completion/cached 为两次之和；取用后归零。
- `tests/test_service.py`：`_account_usage` 把聚合值一次性写入 `cost_llm_tokens`/`cost_tokens`/`cost_prompt_tokens`/`cost_completion_tokens`/`cost_cached_tokens`；负数被钳到 0；cached 不重复计入 total。
- `tests/memory/test_runtime_stores.py`：逐轮 token_ledger 求和 = 会话累计 prompt/completion。
- `tests/harness/test_adapters.py`：`_record_usage` 对 **dict 形态**的 usage 取到 total；total 缺失时用 prompt+completion 兜底；负数被钳到 0。

**窗口/请求预算**：
- 300K/600K/1M 下固定 100K 输入全部通过；
- 128K 下超限输入在 generate 路径抛 `RequestBudgetError`、在 probe 路径转 3003；
- 切换档位后 `runtime_window()`/`runtime_state_budget()` 立即变化。

### 7.2 前端测试

- ModelPicker：新的 4 档显示、切换写入正确值、单档模型禁用；
- ConsoleInput：300K 选项点击后 PUT 载荷正确；
- 全套 `pnpm test`。

### 7.3 新增验证脚本 `scripts/measure_context_tiers.py`

不进入 CI，不写日志文件：

1. 打印常见标称窗口（128K/200K/272K/300K/500K/600K/1M/2M）的档位表；
2. 用固定长历史（2000 轮，同目标）分别以各档位构造 `ContextBudget`，打印 `history_block` 估算 token；
3. 断言随档位递增，token 估算非递减；
4. 可选 `--live`：用同一段长历史调用当前模型，打印 `usage.prompt_tokens/completion_tokens/total_tokens` 与 `cost_llm_tokens`；供应商缓存只影响 cached 字段，不改变 prompt token 口径。

### 7.4 质量门禁

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts/measure_context_tiers.py
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts/measure_context_tiers.py
.\.venv\Scripts\python.exe -m mypy src/devprompt_ai
.\.venv\Scripts\python.exe scripts/check_architecture.py

cd frontend
pnpm typecheck
pnpm test
pnpm build
```

---

## 八、实施顺序

1. 领域层：`window_tiers`/`nearest_context_tier` + 单测；更新 model_spec 投影。
2. 迁移：`normalize_entry` 旧档位归一 + 单测。
3. 预算：`state_budget_for_window` + `AppConfig.runtime_state_budget` + 单测。
4. 接线：service 的 ContextBudget/sensorium/usage；decision `_fit_state`；harness `_record_usage`。
5. 前端夹具与断言更新；跑前端测试。
6. 文档同步（功能清单、架构 §1.6）。
7. 新增 `measure_context_tiers.py`，跑 dry-run，确认 token 单调。
8. 全量门禁 + 可选 live 验证。

---

## 九、假设与决策

| # | 决策 | 理由 |
|---|---|---|
| 1 | 档位不再使用厂商 `context_window_tiers` 生成 UI 选项 | 统一四档策略；厂商字段保留为元数据，避免 5 档/近似重复档 |
| 2 | 最多 4 档；超过时丢最低档 | 用户明确“最多 4 个”；标称值必须保留 |
| 3 | 不足 4 档用 128K 补位 | 用户裁决；避免 272K/200K 模型只有一个选项 |
| 4 | `max_state_tokens` 改为下限，不再固定 30K | 让窗口与 token 消耗正相关；cap 160K 控制成本 |
| 5 | 旧档位取最近合法档（平局取小） | 262K→300K、524K→600K，避免回落 1M 造成跳变 |
| 6 | 窗口仍不发给供应商 | 各协议无标准字段；窗口只驱动本地预算 |
| 7 | current 层仍永不裁 | MUST-25 |
| 8 | 不做全局单档位 | 用户裁决“每模型独立” |

---

## 十、风险与回滚

| 风险 | 缓解 |
|---|---|
| 600K/1M 档位 token 成本上升 | 用户已确认；cap 160K；脚本可量化 |
| 旧档位迁移改变用户选择 | 最近档归一 + 幂等；不删配置；文档说明 |
| 单档模型（128K）选择器禁用 | 既有行为；UI 显示“仅标称窗口” |
| 大 state_budget 让 current 层占比变化 | current 仍按 40% 权重且永不裁；超限只记录 |
| token 统计供应商字段缺失 | total 兜底 prompt+completion；负数钳 0；测试对账 |
| 文档/测试仍写旧阶梯 | 统一更新 128/256/512 断言为 128/300/600/1M |

回滚：改动集中在 `model_spec.py` / `model_migration.py` / `catalog.py` / `budget.py` / `config.py` / `service.py` / `fallback.py` / `llm.py`；无存储结构变更，回退代码即可恢复旧阶梯；旧档位数据会再次被原逻辑接受。

---

## 十一、完成定义（DoD）

- [ ] 四档算法在 128K/200K/272K/300K/500K/600K/1M/1.5M/2M 上输出符合上表，且最多 4 档。
- [ ] 旧档位 262144/524288 在读取时归一为 300K/600K，幂等。
- [ ] `runtime_state_budget()` 在 300K/600K/1M 下为 30K/60K/100K，2M 为 160K。
- [ ] 同一段长历史在 30K/60K/100K 预算下 `history_block` token 单调不减，current 层不随预算变化。
- [ ] token 统计在 dict 形态、total 缺失、负数、cached 场景下不出现偏差；聚合器取用即清零，逐轮账本求和一致。
- [ ] 切换档位后当前激活模型立即使用新窗口与新预算，无需重启。
- [ ] 新档位在 ModelPicker/ConsoleInput 正确显示与写入；单档模型禁用。
- [ ] 全套 pytest/ruff/mypy/架构检查/前端 test+build 绿灯。
- [ ] `measure_context_tiers.py` dry-run 输出档位表与 token 单调结果；可选 live 记录 usage。
