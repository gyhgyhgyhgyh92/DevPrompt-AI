# F-801 第一段 · 候选集召回率实测语料

> **当前状态（2026-10-05）：正式语料已就位。** 5 个真实仓库（click / requests / pinia / axios / headlessui）共 100 条标注已通过 ctags 符号表全量核验，100/100 符号存在且路径精确匹配，标注质量审查全数通过。详见 `标注质量审查报告.md`。
>
> 历史状态（2026-10-04）：曾以 5 个合成 mock 仓库占位验证测量链路。mock 语料的召回率不得作为生死线判定依据，该批mock 仓库仍保留在目录下，仅作链路回归使用。
>
> 复现核验：`python tools/audit_labels.py`（文件/文本层）+ `python tools/audit_labels_ctags.py`（ctags 符号表层）。

## 目录契约

- `manifest.json`：`{"repos": [{"id": "mock-react-admin", "path": "eval/recall/mock-react-admin", "language": "ts", "mock": true}]}`
- `<repo-id>/cases.jsonl`：每行一条 `{"id": "<repo-id>-01", "sentence": "原句", "expected_symbol": "SubmitButton", "expected_path": "src/components.tsx"}`
- `<repo-id>/`：仓库源码（mock 仓库为合成文件；真实接入时替换为仓库路径，cases.jsonl 保留在 `eval/recall/<repo-id>/` 下）

## 标注规范（用户签字项）

1. 每仓 20 条，合计 ≥100 条；原句必须是「真实开发者会写的模糊需求」（含中英混合）
2. `expected_symbol`/`expected_path` 必须是该仓库真实存在且 ctags 可解析的符号（以 `SymbolTableProvider.get` 解析结果为准；标注了 ctags 抽不出的符号属假阴性，剔除并记录）
3. Agent 预标注后，用户抽检 ≥20%（每仓 ≥4 条）并签字；抽检不一致率 >10% 时整仓重标
   - **签字记录**：2026-10-05 用户对真实语料 5 仓全部 100 条逐条审阅后**全量签收**（对话框内逐条输出核对，超出 20% 最低要求）——真实语料标注即为 F-801 正式判定依据
4. 符号总数 <25 的仓库必须在 manifest 中标注 `"small": true`（召回率虚高，报告单独统计）——**全部 mock 仓库均属此类**

## 判定规则

命中 = `expected_symbol` 与 `expected_path` 同时出现在该条原句的 ≤25 条候选中。

## Mock 语料构成（5 仓 × 20 条 = 100 条）

| 仓库 | 语言 | 符号域 | 故意 miss 数（验证报告失败案例渲染） |
|---|---|---|---|
| mock-react-admin | TS/TSX | 组件（提交按钮/用户表格/登录表单/确认弹窗）+ hooks | 每仓 1 条 |
| mock-vue-shop | Vue/TS | 视图（购物车/订单）+ store + API | 每仓 1 条 |
| mock-python-api | Python | FastAPI 路由/模型/依赖 | 每仓 1 条 |
| mock-python-cli | Python | CLI 命令/参数/渲染 | 每仓 1 条 |
| mock-portal-mixed | TS 混合 | 页面/API 客户端/工具 | 每仓 1 条 |

预期 mock 召回率 = 95/100 = 95%（每仓 1 条故意 miss）。该数字仅证明链路与报告渲染正确，**无规格意义**。
