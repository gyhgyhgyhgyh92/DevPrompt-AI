"""F-802 供应商能力冒烟：结构化输出/函数调用/并行工具调用/流式。

遍历 settings.json 的模型注册表（F-604 多模型），逐个跑四项冒烟并输出汇总表；
注册表为空时回退到当前生效配置（.env）。**无 --provider 参数**--用户2026-10-16
裁定「不需要 CLI」，只保留 `python scripts/smoke_provider.py` 一种调用方式。

判定：某供应商四项全 PASS -> 支持；任一 FAIL -> 标记不支持（SHOULD-02）。
退出码：0 = 至少一个供应商全部通过；1 = 有供应商全部失败；2 = 无可用配置。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from agents import Agent, Runner, function_tool
from pydantic import BaseModel

from devprompt_ai.config import AppConfig
from devprompt_ai.domain.model_spec import resolve_api_mode
from devprompt_ai.harness.llm import _ensure_client, build_model  # noqa: PLC2701 -- 冒烟脚本专用
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
    provider: str = ""
    api_mode: str = ""
    param_overrides: dict[str, Any] = field(default_factory=dict)
    temperature: float | None = None
    max_tokens: int | None = None
    is_active: bool = False

    def to_config(self) -> AppConfig:
        """构造仅本条目生效的配置（init 优先级最高，不影响持久化设置）。

        与生产路径同构：provider / api_mode / 参数覆盖一并带出，
        使冒烟测的就是真实调用路径（W4 的模型工厂会按 api_mode 选形态）。
        """
        return AppConfig(
            llm_provider=self.provider,
            llm_base_url=self.base_url,
            llm_api_key=self.api_key,
            llm_model=self.model,
            llm_timeout=self.timeout,
            llm_temperature=self.temperature,
            llm_max_tokens=self.max_tokens,
            api_mode=self.api_mode,
            llm_params=dict(self.param_overrides),
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
                provider=cfg.llm_provider,
                api_mode=cfg.api_mode,
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
                provider=str(entry.get("provider", "")),
                api_mode=str(entry.get("api_mode", "") or ""),
                param_overrides=dict(entry.get("param_overrides") or {}),
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
        model=build_model(cfg),
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
        model=build_model(cfg),
    )
    result = await asyncio.wait_for(Runner.run(agent, "执行", max_turns=6), timeout=cfg.llm_timeout)
    text = str(result.final_output)
    return "3" in text and "7" in text


async def check_streaming(cfg: AppConfig) -> bool:
    agent = Agent(name="smoke-stream", instructions="回复 OK", model=build_model(cfg))
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


#: 准入状态（2026-09-17 裁定：有 key 才实测，无 key 如实标 untested，不伪装可用）
STATUS_SUPPORTED = "支持"
STATUS_UNSUPPORTED = "不支持"
STATUS_UNTESTED = "未经本地验证"


@dataclass
class Report:
    """单个供应商的四项结果。"""

    label: str
    model: str
    provider: str = ""
    api_mode: str = ""
    has_key: bool = True
    results: dict[str, bool] = field(default_factory=dict)
    details: list[str] = field(default_factory=list)

    @property
    def supported(self) -> bool:
        return bool(self.results) and all(self.results.values())

    @property
    def status(self) -> str:
        """三态准入：无 key -> 未经本地验证；有 key 且全过 -> 支持；否则不支持。"""
        if not self.has_key:
            return STATUS_UNTESTED
        return STATUS_SUPPORTED if self.supported else STATUS_UNSUPPORTED


async def probe_target(target: Target) -> Report:
    """跑完一个供应商的四项；单项异常不中断其余项。"""
    report = Report(
        label=target.label,
        model=target.model,
        provider=target.provider,
        api_mode=resolve_api_mode(target.provider, target.api_mode),
        has_key=bool(target.api_key),
    )
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

    print("=== 汇总（provider * api_mode * 模型）===")
    for report in reports:
        mode = report.api_mode or "?"
        print(f"  {report.label:<22}{mode:<26}{report.status}")
    tested = [r for r in reports if r.has_key]
    untested = [r for r in reports if not r.has_key]
    if untested:
        print(f"\n另有 {len(untested)} 个条目无 API Key，未执行实测。")
        print("已如实标「未经本地验证」，不伪装可用；补齐 Key 后重跑本脚本即可纳入准入表。")

    # 错误率护栏：有 key 的条目里若过半失败，多半是网络或配置问题而非供应商能力问题，
    # 此时全量报「不支持」会误导--应保留原始退出码但明确提示先排查环境。
    if tested:
        failed = [r for r in tested if not r.supported]
        if len(failed) * 2 > len(tested):
            print(f"\n[!] 有 Key 的 {len(tested)} 个条目中 {len(failed)} 个失败（过半）。")
            print("  这通常是网络/代理/端点配置问题而非供应商能力问题，")
            print("  建议先核对 base_url 与连通性再下结论。")
    if any(r.supported for r in reports):
        return 0
    return 1 if tested else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
