"""F-802 供应商能力冒烟：结构化输出/函数调用/并行工具调用/流式。

遍历 settings.json 的模型注册表（F-604 多模型），逐个跑四项冒烟并输出汇总表；
注册表为空时回退到当前生效配置（.env）。**无 --provider 参数**——用户2026-10-16
裁定「不需要 CLI」，只保留 `python scripts/smoke_provider.py` 一种调用方式。

判定：某供应商四项全 PASS → 支持；任一 FAIL → 标记不支持（SHOULD-02）。
退出码：0 = 至少一个供应商全部通过；1 = 有供应商全部失败；2 = 无可用配置。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from agents import Agent, Runner, function_tool
from pydantic import BaseModel

from devprompt_ai.config import AppConfig
from devprompt_ai.harness.llm import _ensure_client  # noqa: PLC2701 —— 冒烟脚本专用
from devprompt_ai.memory.settings_store import read_model_registry

PROBE_TIMEOUT = 30.0


class Probe(BaseModel):
    answer: int


@function_tool
def add(a: int, b: int) -> int:
    """两数相加。"""
    return a + b


@function_tool
def shout(text: str) -> str:
    """原样返回大写。"""
    return text.upper()


@dataclass
class Target:
    """一个待测模型条目（来自注册表或当前生效配置）。"""

    label: str
    base_url: str
    model: str
    api_key: str
    timeout: float
    temperature: float | None = None
    max_tokens: int | None = None
    is_active: bool = False

    def to_config(self) -> AppConfig:
        """构造仅本条目生效的配置（init 优先级最高，不影响持久化设置）。"""
        return AppConfig(
            llm_base_url=self.base_url,
            llm_api_key=self.api_key,
            llm_model=self.model,
            llm_timeout=self.timeout,
            llm_temperature=self.temperature,
            llm_max_tokens=self.max_tokens,
            _env_file=None,  # type: ignore[call-arg]
        )


def collect_targets() -> list[Target]:
    """从注册表收集全部条目；注册表为空时回退到当前生效配置。"""
    registry = read_model_registry()
    entries = [m for m in registry.get("models", []) if isinstance(m, dict)]
    if not entries:
        cfg = AppConfig()
        if not (cfg.llm_base_url and cfg.llm_model):
            return []
        return [
            Target(
                label="当前生效配置",
                base_url=cfg.llm_base_url,
                model=cfg.llm_model,
                api_key=cfg.llm_api_key,
                timeout=cfg.llm_timeout,
                is_active=True,
            )
        ]
    active_id = str(registry.get("active_model_id", ""))
    targets: list[Target] = []
    for entry in entries:
        entry_id = str(entry.get("id", ""))
        targets.append(
            Target(
                label=str(entry.get("label") or entry.get("model_id") or entry_id or "未命名"),
                base_url=str(entry.get("base_url", "")),
                model=str(entry.get("model_id", "")),
                api_key=str(entry.get("api_key", "")),
                timeout=float(entry.get("timeout") or PROBE_TIMEOUT),
                is_active=entry_id == active_id,
            )
        )
    return targets


def _cfg_for(target: Target) -> AppConfig:
    return target.to_config()


async def check_structured(cfg: AppConfig) -> bool:
    """走项目实际调用路径（chat_structured 含 F-004 适配层），而非裸 SDK output_type。"""
    from devprompt_ai.harness.llm import chat_structured

    out = await asyncio.wait_for(
        chat_structured(cfg, Probe, "只输出 JSON", "计算 2+3，把结果填入 answer 字段"),
        timeout=cfg.llm_timeout,
    )
    return out.answer == 5


async def check_tool_call(cfg: AppConfig) -> bool:
    agent = Agent(
        name="smoke-tool",
        instructions="必须使用 add 工具计算 2+3",
        tools=[add],
        model=cfg.llm_model,
    )
    result = await asyncio.wait_for(
        Runner.run(agent, "2+3=?", max_turns=3), timeout=cfg.llm_timeout
    )
    return "5" in str(result.final_output)


async def check_parallel_tools(cfg: AppConfig) -> bool:
    agent = Agent(
        name="smoke-para",
        instructions="同时用 add(1,2) 与 add(3,4)，再各自调用 shout 报告结果",
        tools=[add, shout],
        model=cfg.llm_model,
    )
    result = await asyncio.wait_for(Runner.run(agent, "执行", max_turns=6), timeout=cfg.llm_timeout)
    text = str(result.final_output)
    return "3" in text and "7" in text


async def check_streaming(cfg: AppConfig) -> bool:
    agent = Agent(name="smoke-stream", instructions="回复 OK", model=cfg.llm_model)
    streamed = Runner.run_streamed(agent, "回复 OK")  # 同步流对象，禁 await
    deltas = 0
    event_types: set[str] = set()
    async for event in streamed.stream_events():
        event_types.add(type(event).__name__)
        inner = getattr(event, "data", None)
        if inner is not None:
            inner_name = type(inner).__name__
            event_types.add(f"data:{inner_name}")
            has_delta = bool(getattr(inner, "delta", None)) or "delta" in inner_name.lower()
            if has_delta:
                deltas += 1
    if deltas == 0:
        print(f"    detail: deltas=0, event_types={sorted(event_types)}")
    return deltas > 0


#: 四项冒烟（F-802）。顺序即执行顺序，输出按此列展示。
CHECKS: tuple[tuple[str, Any], ...] = (
    ("structured_output", check_structured),
    ("tool_call", check_tool_call),
    ("parallel_tools", check_parallel_tools),
    ("streaming", check_streaming),
)


@dataclass
class Report:
    """单个供应商的四项结果。"""

    label: str
    model: str
    results: dict[str, bool] = field(default_factory=dict)
    details: list[str] = field(default_factory=list)

    @property
    def supported(self) -> bool:
        return bool(self.results) and all(self.results.values())


async def probe_target(target: Target) -> Report:
    """跑完一个供应商的四项；单项异常不中断其余项。"""
    report = Report(label=target.label, model=target.model)
    cfg = _cfg_for(target)
    try:
        _ensure_client(cfg)
    except Exception as exc:  # noqa: BLE001 - 配置无效即该供应商不可用
        report.details.append(f"client init failed: {type(exc).__name__}")
        report.results = {name: False for name, _ in CHECKS}
        return report
    for name, check in CHECKS:
        try:
            report.results[name] = bool(await check(cfg))
        except Exception as exc:  # noqa: BLE001 - 冒烟需捕获供应商侧任意异常
            report.results[name] = False
            detail = f"{name}: {exc!r}"
            report.details.append(detail[:200])
    return report


async def main_async() -> int:
    targets = collect_targets()
    if not targets:
        print("SKIP: 注册表为空且当前生效配置缺少 LLM_BASE_URL/LLM_MODEL")
        return 2
    print(f"待测供应商 {len(targets)} 个（当前生效项以 * 标注）\n")
    reports: list[Report] = []
    for target in targets:
        marker = "*" if target.is_active else " "
        print(f"[{marker}] {target.label}（{target.model} @ {target.base_url}）")
        report = await probe_target(target)
        for name, _ in CHECKS:
            mark = "PASS" if report.results.get(name) else "FAIL"
            print(f"      {name:<18}{mark}")
        for detail in report.details:
            print(f"      {detail}")
        reports.append(report)
        print()

    print("=== 汇总 ===")
    for report in reports:
        state = "支持" if report.supported else "不支持"
        print(f"  {report.label:<24}{state}")
    if any(r.supported for r in reports):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
