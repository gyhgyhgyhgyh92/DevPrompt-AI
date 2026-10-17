"""Step 0.3：真实 LLM 输出形态统计——测量 Batch 0 探针识别的脆弱形态的实际发生率。

为什么要真实统计：离线探针只能证明「当前实现在这类输入下会失败」，不能证明
「LLM 真的会这样输出」。本脚本绕过 `chat_structured`（它会把解析失败的重试结果
吞掉，只返回成功解析的对象），直接调用底层 Agent 并读取**原始输出文本**。

成本控制：默认 20 次，单次调用只发最小 schema（两个字符串字段），
指令刻意要求附带说明以提高观察窗口。

密钥处理：只经 AppConfig 读取，绝不打印、绝不写入任何输出文件（MUST-19）。

⚠️ **口径说明（2026-09-17 多供应商扩展后刻意保留 chat 形态）**：
生产路径已改为按 provider 分流（`harness/llm.build_model` 逐调用注入 Model 实例，
不再用 `set_default_openai_api` 全局开关）。但本脚本**故意固定 `chat_completions`**：

它是 Batch 0「M-1 解析加固降级」的**复活条件探针**——当时记录的数据全部来自
chat 形态（40 次调用，脆弱形态命中率 0/40）。若跟着生产路径改为 responses，
新旧数据口径不可比，降级结论就失去依据。真正需要测新形态时，另起脚本，
不要改这个。

"""

from __future__ import annotations

import asyncio
import collections
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pydantic import BaseModel  # noqa: E402

from devprompt_ai.config import AppConfig  # noqa: E402

SAMPLE_COUNT = 20

_SYSTEM = (
    "你是代码审查助手。请判断检索结果是否命中目标符号。只输出一个 JSON 对象，"
    "包含 verdict 与 reason 两个字符串字段。回答时请先简要说明判断依据。"
)


class _Probe(BaseModel):
    """最小 schema：字段少则输出短，观察窗口更大。"""

    verdict: str
    reason: str


_SCHEMA = _Probe.model_json_schema()


def balanced_end(text: str, start: int) -> int:
    """从 start 处的左括号起返回配平位置；未配平返回 -1。

    统计用途的简化版（不处理字符串内的括号）；Batch 3 的 M-1 会实现严谨版。
    """
    depth = 0
    for idx in range(start, len(text)):
        if text[idx] == "{":
            depth += 1
        elif text[idx] == "}":
            depth -= 1
            if depth == 0:
                return idx
    return -1


def classify(raw: str) -> str:
    """按 Batch 0 探针的 real 级脆弱形态分类原始输出。"""
    stripped = raw.strip()
    if not stripped.startswith("{"):
        blocks = re.findall(r"```(?:\w*)\s*(.*?)```", stripped, re.DOTALL)
        if blocks and not blocks[0].strip().startswith("{"):
            return "首个围栏块是说明文字"
        return "非 JSON 开头"
    end = balanced_end(stripped, 0)
    if end < 0:
        return "JSON 未闭合"
    tail = stripped[end + 1 :].strip()
    if not tail:
        return "干净单块 JSON"
    if "{" in tail:
        return "尾部解释文字含花括号"
    return "尾部有解释文字但无花括号"


async def raw_call(cfg: AppConfig, user: str, system: str, schema: object) -> str:
    """绕过 chat_structured 直接取原始输出文本（否则解析失败会被重试吞掉）。"""
    from agents import Agent, ModelSettings, Runner, set_default_openai_api, set_tracing_disabled

    set_default_openai_api("chat_completions")
    set_tracing_disabled(True)
    instructions = (
        system + "\n\n输出要求：只输出一个 JSON 对象，且必须符合如下 JSON Schema：\n" + str(schema)
    )
    agent = Agent(
        name="probe",
        instructions=instructions,
        model=cfg.llm_model,
        model_settings=ModelSettings(
            temperature=cfg.llm_temperature, max_tokens=cfg.llm_max_tokens
        ),
    )
    result = await asyncio.wait_for(Runner.run(agent, user, max_turns=1), timeout=cfg.llm_timeout)
    return str(result.final_output)


def real_prompts() -> tuple[str, str]:
    """复用项目**真实**的三套生成 prompt（harness.llm 私有构造器）。

    为什么必须用真实 prompt：首轮统计用最小 schema 测得 0/20，但该 prompt 与项目
    实际使用的 `_build_multi_system`（含档位约束、一致性约束、梯度约束）差异过大，
    结论不能代表真实场景。输出越长、约束越多，模型附带外部说明的概率也越高。
    """
    from typing import Literal

    from devprompt_ai.domain.generate.ports import GenerationContext
    from devprompt_ai.harness.llm import _build_multi_system, _build_multi_user

    ctx = GenerationContext(
        sentence="把提交按钮改成primary-500 主色，并补一个导出 CSV 的次要按钮",
        project_root="D:/ws/repo",
        level="C",
        facts_summary=(
            "SubmitButton 定义于 src/ui/button.tsx:12（导出 const SubmitButton = () => <button "
            'className="btn" />）\n--color-primary-500 已定义于 src/styles/tokens.css:1'
        ),
        clarifications={"target_symbol": "SubmitButton"},
        conservative=False,
    )
    levels: list[Literal["A", "B", "C"]] = ["A", "B", "C"]
    return _build_multi_system(levels), _build_multi_user(ctx, levels)


async def main() -> int:
    from devprompt_ai.domain.generate.ports import MultiVariantDraft
    from devprompt_ai.harness.llm import _ensure_client, _parse_model

    cfg = build_config()
    host = cfg.llm_base_url.rsplit("/", 1)[-1]
    use_real = "--real-prompt" in sys.argv
    output_type: type[BaseModel]
    if use_real:
        system, user = real_prompts()
        output_type = MultiVariantDraft
    else:
        system = _SYSTEM
        user = "检索结果：SubmitButton 定义位于 src/ui/button.tsx:12。"
        output_type = _Probe

    print(f"模型：{cfg.llm_model}（base_url 末段 {host}）")
    print(f"模式：{'项目真实三套生成 prompt' if use_real else '最小 schema 探针'}")
    print(f"样本数：{SAMPLE_COUNT}\n")

    tally: collections.Counter[str] = collections.Counter()
    parse_fail = 0

    for i in range(SAMPLE_COUNT):
        _ensure_client(cfg)
        try:
            raw = await raw_call(cfg, user, system, output_type.model_json_schema())
        except Exception as exc:  # noqa: BLE001 - 统计脚本需容忍单次失败
            print(f"  [{i + 1:>2}/{SAMPLE_COUNT}] 调用失败：{type(exc).__name__}")
            continue
        kind = classify(raw)
        tally[kind] += 1
        if _parse_model(output_type, raw) is None:
            parse_fail += 1
        print(f"  [{i + 1:>2}/{SAMPLE_COUNT}] {kind}")

    print("\n=== 输出形态分布 ===")
    for kind, count in tally.most_common():
        print(f"  {kind:<26}{count}/{SAMPLE_COUNT}")
    vulnerable = sum(c for k, c in tally.items() if "花括号" in k or "围栏" in k)
    print(f"\n命中 real 级脆弱形态：{vulnerable}/{SAMPLE_COUNT}")
    print(f"其中实际解析失败：{parse_fail}/{SAMPLE_COUNT}")
    if vulnerable == 0:
        print("→ 真实模型未表现出该倾向，M-1 收益存疑，建议降级")
    else:
        print("→ 真实模型确实会这样输出，M-1 有实际收益")
    return 0


def dotenv_overrides() -> dict[str, str]:
    """只读解析 .env 的 LLM 三键。

    为什么需要：AppConfig 加载链为 init > 进程环境 > 本地设置(settings.json) > .env。
    而 settings.json 里当前生效的是 UI 测试留下的占位端点（api.example.com），
    会覆盖 .env 的真实配置。统计须用真实端点，故经 init 参数只读覆盖——
    **不写回settings.json，不改动任何持久化配置**（MUST-19）。
    """
    path = Path(__file__).resolve().parents[1] / ".env"
    wanted = {
        "LLM_BASE_URL": "llm_base_url",
        "LLM_API_KEY": "llm_api_key",
        "LLM_MODEL": "llm_model",
    }
    found: dict[str, str] = {}
    if not path.is_file():
        return found
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        field = wanted.get(key.strip())
        if field and value.strip():
            found[field] = value.strip()
    return found


def build_config() -> AppConfig:
    """用 .env 的真实端点构造配置；三键缺一则回退默认加载链。"""
    found = dotenv_overrides()
    if {"llm_base_url", "llm_api_key", "llm_model"} <= found.keys():
        cfg = AppConfig(
            llm_base_url=str(found["llm_base_url"]),
            llm_api_key=str(found["llm_api_key"]),
            llm_model=str(found["llm_model"]),
        )
    else:
        cfg = AppConfig()
    cfg.validate()
    return cfg


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
