"""多模型路由链（G2/G6/G9）测试：候选解析、bandit 主选、主备降级与单候选退化。"""

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
def _clean_stats_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    invalidate_routing_stats_cache()
    # 禁用 ε-探索：路由测试要求主选确定（平手按注册顺序）
    import devprompt_ai.domain.model.routing as routing_mod

    monkeypatch.setattr(routing_mod, "should_explore", lambda *a, **k: False)


def _entry(entry_id: str, model_id: str) -> dict[str, object]:
    return {
        "id": entry_id,
        "provider": "deepseek",
        "model_id": model_id,
        "api_key": "k-" + entry_id,
        "base_url": f"https://api.example.com/{entry_id}",
        "api_mode": "",
    }


async def test_single_candidate_degrades_to_current_cfg(monkeypatch: pytest.MonkeyPatch) -> None:
    """候选 ≤1（含空表）时退化为现状路径：链上只有原 cfg，行为字节级对等。"""
    monkeypatch.setattr(llm_mod, "load_candidates", lambda: [])
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]

    assert await _resolve_chain(cfg, purpose="generate") == [cfg]


async def test_multi_candidates_bandit_prefers_primary_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm_mod, "load_candidates", lambda: [_entry("a", "model-a"), _entry("b", "model-b")]
    )
    # 无统计 → 平手按传入顺序，主 = 注册表第一个
    monkeypatch.setattr(llm_mod, "load_routing_stats", _stats_stub({}))

    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    chain = await _resolve_chain(cfg, purpose="probe")

    assert [c.llm_model for c in chain] == ["model-a", "model-b"]
    assert chain[0].llm_base_url.endswith("/a")
    assert chain[0].llm_api_key == "k-a"


async def test_multi_candidates_bandit_uses_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm_mod, "load_candidates", lambda: [_entry("a", "model-a"), _entry("b", "model-b")]
    )
    # model-a 探针 2 连败且慢，model-b 全胜 → bandit 应把 b 排前
    monkeypatch.setattr(
        llm_mod,
        "load_routing_stats",
        _stats_stub(
            {
                ("model-a", "probe"): (2, 0, 40_000),
                ("model-b", "probe"): (2, 2, 2_000),
            }
        ),
    )

    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    chain = await _resolve_chain(cfg, purpose="probe")

    assert [c.llm_model for c in chain] == ["model-b", "model-a"]


async def test_model_override_pins_exact_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm_mod, "load_candidates", lambda: [_entry("a", "model-a"), _entry("b", "model-b")]
    )

    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]
    pinned = await _resolve_chain(cfg, purpose="generate", model_id="b")
    unknown = await _resolve_chain(cfg, purpose="generate", model_id="missing")

    assert [c.llm_model for c in pinned] == ["model-b"]
    assert unknown == [cfg], "未知覆盖 id 退化为现状，不得臆造模型"


async def test_failover_switches_to_next_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """可降级失败（限流）→ 换链上下一个；成功后原样返回。"""
    monkeypatch.setattr(
        llm_mod, "load_candidates", lambda: [_entry("a", "model-a"), _entry("b", "model-b")]
    )
    monkeypatch.setattr(llm_mod, "load_routing_stats", _stats_stub({}))
    calls: list[str] = []

    async def fake_once(cfg: AppConfig, *_args: object, **_kw: object) -> _Probe:
        calls.append(cfg.llm_model)
        if cfg.llm_model == "model-a":
            code = next(c for s, c in llm_mod._LLM_FAILURE_CODES.items() if s == "rate_limit")
            raise llm_mod.GenerationError("rate limited", code=code, context={})
        return _Probe()

    monkeypatch.setattr(llm_mod, "_structured_once", fake_once)
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]

    result = await chat_structured(cfg, _Probe, "sys", "user")

    assert result.value == "ok"
    assert calls == ["model-a", "model-b"]


async def test_auth_failure_does_not_failover(monkeypatch: pytest.MonkeyPatch) -> None:
    """额度/鉴权类失败换模型救不了：直接抛，不打扰备选。"""
    monkeypatch.setattr(
        llm_mod, "load_candidates", lambda: [_entry("a", "model-a"), _entry("b", "model-b")]
    )
    monkeypatch.setattr(llm_mod, "load_routing_stats", _stats_stub({}))
    calls: list[str] = []

    async def fake_once(cfg: AppConfig, *_args: object, **_kw: object) -> _Probe:
        calls.append(cfg.llm_model)
        code = next(c for s, c in llm_mod._LLM_FAILURE_CODES.items() if s == "invalid_api_key")
        raise llm_mod.GenerationError("bad key", code=code, context={})

    monkeypatch.setattr(llm_mod, "_structured_once", fake_once)
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]

    with pytest.raises(llm_mod.GenerationError):
        await chat_structured(cfg, _Probe, "sys", "user")
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
    monkeypatch.setattr(llm_mod, "load_routing_stats", _stats_stub({}))
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
    cfg = AppConfig(_env_file=None)  # type: ignore[call-arg]

    result = await chat_structured(cfg, _Probe, "sys", "user")

    assert result.value == "ok"
    assert calls == ["model-a", "model-b"]


async def test_routing_stats_recorded_per_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """G9：每次尝试落账（成功/失败与耗时），供 bandit 下次决策。"""
    db_path = str(tmp_path) + "/ledger.db"  # type: ignore[operator]
    cfg = AppConfig(  # type: ignore[call-arg]
        _env_file=None,
        db_path=db_path,
        llm_model="model-x",
        llm_base_url="https://api.example.com/x",
        llm_api_key="k-x",
    )
    monkeypatch.setattr(llm_mod, "load_candidates", lambda: [])
    monkeypatch.setattr(llm_mod, "load_routing_stats", _stats_stub({}))

    async def fake_run(agent: object, user: str, timeout: float) -> object:
        class _R:
            final_output = '{"value": "ok"}'
            usage = None

        return _R()

    monkeypatch.setattr(llm_mod, "_run_with_retry", fake_run)

    await chat_structured(cfg, _Probe, "sys", "user", purpose="probe")

    stats = await SQLiteRoutingStats(db_path).load_all()
    assert stats[("model-x", "probe")][0] == 1
    assert stats[("model-x", "probe")][1] == 1


def _stats_stub(data: dict[tuple[str, str], tuple[int, int, int]]) -> object:
    """构造 load_routing_stats 的异步替身（返回固定统计）。"""

    async def _load(_db_path: str) -> dict[tuple[str, str], tuple[int, int, int]]:
        return data

    return _load
