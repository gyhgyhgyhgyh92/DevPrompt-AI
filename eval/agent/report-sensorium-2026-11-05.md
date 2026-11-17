# 六维感知与声明率统计

## 样本

| 项 | 值 |
| --- | --- |
| 轮次总数 | 23 |
| 带六维快照的轮次 | 3 |
| DONE / ABORTED | 3 / 0 |
| C 档轮次 / 其中空声明 | 0 / 0 |
| 记录到 token 的轮次 | 3 |

## 六维分布

| 维度 | n | p50 | p95 | min | max |
| --- | --- | --- | --- | --- | --- |
| momentum | 3 | 1.0 | 1.0 | 1.0 | 1.0 |
| pressure | 3 | 0.1667 | 0.1667 | 0.125 | 0.1667 |
| coverage | 3 | 0.7143 | 0.9714 | 0.7143 | 1.0 |
| complexity | 3 | 0.6667 | 0.6667 | 0.5283 | 0.6667 |
| familiarity | 3 | 0.5 | 0.5 | 0.24 | 0.5 |
| stability | 3 | 0.875 | 0.875 | 0.8333 | 0.875 |
| score | 3 | 0.6952 | 0.7361 | 0.6668 | 0.7407 |

## 接线判定（六维是否升级为熔断第四判据）

| 项 | 值 | 门槛 |
| --- | --- | --- |
| 有效样本 | 3 | ≥ 20 |
| 异常组样本（ABORTED 组） | 0 | ≥ 3 |
| DONE 组 score 中位数 | 0.6952 | — |
| 异常组 score 中位数 | 0.0 | — |
| 两组 score 中位数差 | 0.0 | ≥ 0.15 |

**结论：不接线**（门槛未全部满足），保持 shadow 观测。

## 断言声明率（claim_strict 是否收紧）

- C 档轮次 0，其中一条引用都没声明 0 轮，声明率缺口 0.0。
- 口径：`undeclared` 为真即视为空声明（claim_strict 打开后会因此把 C 降为 B）。

## 成本护栏上限建议（FOLLOWUP_COST_BUDGET）

- 每轮 LLM token：p50 3452.0 / p95 3571.7 / max 3585.0
- 建议上限 **30000** token（口径：max(30000, ceil(p95×1.5))，按 5000 取整）。

## 本轮实际情况（2026-11-05）

| 项 | 说明 |
| --- | --- |
| 样本来源 | 真实会话采集（`scripts/smoke_real_llm.py`，真实仓 `eval/repos/{click,requests,axios}`），落 `./.logs/sensorium-sample.db` |
| 采集条数 | 计划 21 条，**实际有效 3 条**：其余 18 条因供应商 402（余额耗尽）失败 |
| 六维接线 | **不接线**，保持 shadow。有效样本 3 < 门槛 20，且无 ABORTED 轮次、无法验证分离度 |
| 声明率 | **无法计算**：3 个 DONE 轮 `facts_complete=false` → 档位 B，而分母是 C 档轮次 → `claim_strict` 保持灰度关闭 |
| 成本护栏 | **已启用为 30000 token**（≈8~9 个完整轮；实测单轮 p50 3.4k / p95 3.6k）；样本仅 3 条，标注「待复核」 |

### 复核步骤（余额恢复后）

```powershell
# 1) 独占补采样本（禁止与其它 LLM 任务并发，并发会打崩上游并作废数据）
uv run python scripts/smoke_real_llm.py --project-root eval/repos/click --sentence "<原句>" --db-path ./.logs/sensorium-sample.db
# 2) 重算分布与接线判定
uv run python scripts/measure_sensorium.py --db-path ./.logs/sensorium-sample.db --out eval/agent/report-sensorium-2026-11-05.md
```

### 已知偏差（必须随结论一起读）

1. **护栏启用会改变六维分布**：`pressure` 维度在 `cost_budget > 0` 时按 `cost_tokens / cost_budget` 加权（`domain/agent/sensorium.py:87-92`）。本报告的 pressure 分布采自 `cost_budget = 0`（只看步数）→ 接线阈值标定必须在护栏启用后重采一次。
2. **样本量仅 3 条**：p50/p95 只能当量级参考，不能当标定结论。
3. **异常组为代理口径**：本次无 ABORTED 轮次，脚本退用「最低四分位组」；接线判定本就未通过，故未据此下任何结论。
