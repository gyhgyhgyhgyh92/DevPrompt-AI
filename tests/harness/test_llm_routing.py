"""多模型候选链（确定性）测试：主选解析、主备降级与单候选退化。

2026-11-15 用户裁定：候选链不再随机/按胜率排序——主模型只由
「注册表激活条目 → 首个可用条目」确定性解析，其余条目仅作固定顺序 failover。
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from devprompt_ai.config import AppConfig
from devprompt_ai.harness import llm as llm_mod
from devprompt_ai.harness.llm import _FAILOVER_CODES, _resolve_chain, chat_structured
from devprompt_ai.harness.model_candidates import invalidate_routing_stats_cache
from devprompt_ai.memory.routing_stats import SQLiteRoutingStats


class _Probe(BaseModel):
    value: str = "ok"


@pytest.fixture(autouse=True)
def _clean_stats_cache() -> None:
    invalidate_routing_stats_cache()


def _entry(entry_id: str, model_id: str) -> dict[str, object]:
    return {
        "id": entry_id,
        "provider": "deepseek",
        "model_id": model_id,
        "api_key": "k-" + entry_id,
        "base_url": f"https://api.example.com/{entry_id}",
        "api_mode": "",
    }


def _cfg(**overrides: object) -> AppConfig:
    """启用多路由的配置：候选链才会展开为多条目。"""
    fields: dict[str, object] = {"multi_model_routing": True}
    fields.update(overrides)
    return AppConfig(_env_file=None, **fields)  # type: ignore[call-arg]


def _active(active_id: str) -> object:
    """构造 read_model_registry 的替身（只关心激活位）。"""

    def _read() -> dict[str, object]:
        return {"providers": [], "models": [], "active_model_id": active_id}

    return _read


async def test_single_candidate_degrades_to_current_cfg(monkeypatch: pytest.MonkeyPatch) -> None:
    """候选 ≤1（含空表）时退化为现状路径：链上只有原 cfg，行为字节级对等。"""
    monkeypatch.setattr(llm_mod, "load_candidates", lambda: [])
    cfg = _cfg()

    assert await _resolve_chain(cfg) == [cfg]


async def test_multi_candidates_primary_from_registry_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未设激活模型：注册表首个可用条目置首，其余按注册顺序（确定性）。"""
    monkeypatch.setattr(
        llm_mod, "load_candidates", lambda: [_entry("a", "model-a"), _entry("b", "model-b")]
    )
    monkeypatch.setattr(llm_mod, "read_model_registry", _active(""))

    chain = await _resolve_chain(_cfg())

    assert [c.llm_model for c in chain] == ["model-a", "model-b"]
    assert chain[0].llm_base_url.endswith("/a")
    assert chain[0].llm_api_key == "k-a"


async def test_active_model_placed_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """激活条目命中（按 id 或 model_id）→ 置首；其余条目按注册顺序作为 failover。"""
    monkeypatch.setattr(
        llm_mod, "load_candidates", lambda: [_entry("a", "model-a"), _entry("b", "model-b")]
    )
    monkeypatch.setattr(llm_mod, "read_model_registry", _active("b"))

    chain = await _resolve_chain(_cfg())

    assert [c.llm_model for c in chain] == ["model-b", "model-a"]


async def test_active_model_resolves_by_model_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """激活位按 model_id 也能命中（注册表里 id 与 model_id 可能不同）。"""
    monkeypatch.setattr(
        llm_mod, "load_candidates", lambda: [_entry("a", "model-a"), _entry("b", "model-b")]
    )
    monkeypatch.setattr(llm_mod, "read_model_registry", _active("model-b"))

    chain = await _resolve_chain(_cfg())

    assert [c.llm_model for c in chain] == ["model-b", "model-a"]


async def test_unknown_active_falls_back_to_first_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """激活位指向已删除条目 → 回落注册表首个条目，不臆造模型、不随机。"""
    monkeypatch.setattr(
        llm_mod, "load_candidates", lambda: [_entry("a", "model-a"), _entry("b", "model-b")]
    )
    monkeypatch.setattr(llm_mod, "read_model_registry", _active("missing"))

    chain = await _resolve_chain(_cfg())

    assert [c.llm_model for c in chain] == ["model-a", "model-b"]


async def test_chain_is_stable_across_repeated_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """多次解析结果完全一致（无随机探索）。"""
    monkeypatch.setattr(
        llm_mod, "load_candidates", lambda: [_entry("a", "model-a"), _entry("b", "model-b")]
    )
    monkeypatch.setattr(llm_mod, "read_model_registry", _active(""))

    orders = {tuple(c.llm_model for c in await _resolve_chain(_cfg())) for _ in range(5)}

    assert orders == {("model-a", "model-b")}


async def test_failover_switches_to_next_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """可降级失败（限流）→ 换链上下一个；成功后原样返回。"""
    monkeypatch.setattr(
        llm_mod, "load_candidates", lambda: [_entry("a", "model-a"), _entry("b", "model-b")]
    )
    monkeypatch.setattr(llm_mod, "read_model_registry", _active(""))
    calls: list[str] = []

    async def fake_once(cfg: AppConfig, *_args: object, **_kw: object) -> _Probe:
        calls.append(cfg.llm_model)
        if cfg.llm_model == "model-a":
            code = next(c for s, c in llm_mod._LLM_FAILURE_CODES.items() if s == "rate_limit")
            raise llm_mod.GenerationError("rate limited", code=code, context={})
        return _Probe()

    monkeypatch.setattr(llm_mod, "_structured_once", fake_once)

    result = await chat_structured(_cfg(), _Probe, "sys", "user")

    assert result.value == "ok"
    assert calls == ["model-a", "model-b"]


async def test_auth_failure_does_not_failover(monkeypatch: pytest.MonkeyPatch) -> None:
    """额度/鉴权类失败换模型救不了：直接抛，不打扰备选。"""
    monkeypatch.setattr(
        llm_mod, "load_candidates", lambda: [_entry("a", "model-a"), _entry("b", "model-b")]
    )
    monkeypatch.setattr(llm_mod, "read_model_registry", _active(""))
    calls: list[str] = []

    async def fake_once(cfg: AppConfig, *_args: object, **_kw: object) -> _Probe:
        calls.append(cfg.llm_model)
        code = next(c for s, c in llm_mod._LLM_FAILURE_CODES.items() if s == "invalid_api_key")
        raise llm_mod.GenerationError("bad key", code=code, context={})

    monkeypatch.setattr(llm_mod, "_structured_once", fake_once)

    with pytest.raises(llm_mod.GenerationError):
        await chat_structured(_cfg(), _Probe, "sys", "user")
    assert calls == ["model-a"]


def test_failover_codes_exclude_auth_only() -> None:
    """鉴权失败不降级；余额不足降级（条目可能属于不同账户）。"""
    assert 5014 not in _FAILOVER_CODES
    assert 5013 in _FAILOVER_CODES


async def test_quota_failure_failovers_to_next_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """余额不足（5013）→ 换链上下一个候选；成功后原样返回。"""
    monkeypatch.setattr(
        llm_mod, "load_candidates", lambda: [_entry("a", "model-a"), _entry("b", "model-b")]
    )
    monkeypatch.setattr(llm_mod, "read_model_registry", _active(""))
    calls: list[str] = []

    async def fake_once(cfg: AppConfig, *_args: object, **_kw: object) -> _Probe:
        calls.append(cfg.llm_model)
        if cfg.llm_model == "model-a":
            code = next(
                c for s, c in llm_mod._LLM_FAILURE_CODES.items() if s == "insufficient_quota"
            )
            raise llm_mod.GenerationError("insufficient balance", code=code, context={})
        return _Probe()

    monkeypatch.setattr(llm_mod, "_structured_once", fake_once)

    result = await chat_structured(_cfg(), _Probe, "sys", "user")

    assert result.value == "ok"
    assert calls == ["model-a", "model-b"]


async def test_routing_stats_recorded_per_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """G9：每次尝试落账（成功/失败与耗时），仅供观测，不参与候选选择。"""
    db_path = str(tmp_path) + "/ledger.db"  # type: ignore[operator]
    cfg = AppConfig(  # type: ignore[call-arg]
        _env_file=None,
        db_path=db_path,
        llm_model="model-x",
        llm_base_url="https://api.example.com/x",
        llm_api_key="k-x",
    )
    monkeypatch.setattr(llm_mod, "load_candidates", lambda: [])

    async def fake_run(agent: object, payload: object, timeout: float, **_kw: object) -> object:
        class _R:
            final_output = '{"value": "ok"}'
            usage = None

        return _R()

    monkeypatch.setattr(llm_mod, "_run_with_retry", fake_run)

    await chat_structured(cfg, _Probe, "sys", "user", purpose="probe")

    stats = await SQLiteRoutingStats(db_path).load_all()
    assert stats[("model-x", "probe")][0] == 1
    assert stats[("model-x", "probe")][1] == 1
