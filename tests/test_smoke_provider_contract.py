"""供应商冒烟脚本的编排契约测试（N-9）。

只测**编排逻辑**（收集目标、逐项跑、汇总判定）；真实 LLM 调用需要密钥，由脚本本身
在无配置时给出 SKIP，不在单测里打真实网络。

关键回归点：
1. 注册表有条目时**逐条**收集（不是只测active 那一条）
2. 注册表为空时回退当前生效配置（用户 2026-10-16 裁定）
3. 单项异常**不中断**其余检查（F-802 的四项都要有结论）
4. 不提供 --provider 参数（用户裁定「不需要 CLI」）
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import smoke_provider as sp  # noqa: E402


def _registry(
    monkeypatch: pytest.MonkeyPatch, entries: list[dict[str, object]], active: str = ""
) -> None:
    monkeypatch.setattr(
        sp, "read_model_registry", lambda: {"models": entries, "active_model_id": active}
    )


def _entry(idx: int, **over: object) -> dict[str, object]:
    base = {
        "id": f"m-{idx}",
        "label": f"模型{idx}",
        "base_url": f"https://example{idx}.com/v1",
        "model_id": f"mdl-{idx}",
        "api_key": f"key-{idx}",
        "timeout": 30,
    }
    return {**base, **over}


class TestCollectTargets:
    def test_collects_every_registry_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """回归点 1：逐条收集，不是只测当前生效那一条。"""
        _registry(monkeypatch, [_entry(1), _entry(2), _entry(3)], active="m-2")
        targets = sp.collect_targets()
        assert len(targets) == 3
        assert [t.model for t in targets] == ["mdl-1", "mdl-2", "mdl-3"]

    def test_marks_active_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _registry(monkeypatch, [_entry(1), _entry(2)], active="m-2")
        targets = sp.collect_targets()
        assert [t.is_active for t in targets] == [False, True]

    def test_falls_back_to_active_config_when_registry_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """回归点 2：注册表为空时回退当前生效配置（用户裁定）。"""
        _registry(monkeypatch, [])
        monkeypatch.setenv("LLM_BASE_URL", "https://fallback.example.com/v1")
        monkeypatch.setenv("LLM_API_KEY", "fallback-key")
        monkeypatch.setenv("LLM_MODEL", "fallback-model")
        monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", "")
        targets = sp.collect_targets()
        assert len(targets) == 1
        assert targets[0].label == "当前生效配置"
        assert targets[0].model == "fallback-model"

    def test_returns_empty_when_nothing_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _registry(monkeypatch, [])
        monkeypatch.setenv("LLM_BASE_URL", "")
        monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", "")
        assert sp.collect_targets() == []

    def test_skips_malformed_entries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _registry(monkeypatch, [_entry(1), "not-a-dict", _entry(2)])  # type: ignore[list-item]
        assert len(sp.collect_targets()) == 2


class TestTargetConfig:
    def test_builds_entry_scoped_config(self) -> None:
        target = sp.Target(
            label="x", base_url="https://a.com/v1", model="m", api_key="k", timeout=12.0
        )
        cfg = target.to_config()
        assert cfg.llm_base_url == "https://a.com/v1"
        assert cfg.llm_model == "m"
        assert cfg.llm_timeout == 12.0


class TestProbeTarget:
    def test_single_failure_does_not_abort_others(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """回归点 3：四项都要有结论，一项炸了其余照跑。"""
        target = sp.Target(label="t", base_url="https://a.com", model="m", api_key="k", timeout=5.0)
        monkeypatch.setattr(sp, "_ensure_client", lambda _c: None)

        async def boom(_cfg: object) -> bool:
            raise RuntimeError("nope")

        async def ok(_cfg: object) -> bool:
            return True

        checks = (
            ("structured_output", boom),
            ("tool_call", ok),
            ("parallel_tools", ok),
            ("streaming", ok),
        )
        monkeypatch.setattr(sp, "CHECKS", checks)

        report = asyncio.run(sp.probe_target(target))
        assert report.results["structured_output"] is False
        assert report.results["tool_call"] is True
        assert report.supported is False, "有任一 FAIL 即不支持"

    def test_all_pass_marks_supported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        target = sp.Target(label="t", base_url="https://a.com", model="m", api_key="k", timeout=5.0)
        monkeypatch.setattr(sp, "_ensure_client", lambda _c: None)

        async def ok(_cfg: object) -> bool:
            return True

        monkeypatch.setattr(sp, "CHECKS", (("a", ok), ("b", ok)))
        report = asyncio.run(sp.probe_target(target))
        assert report.supported is True

    def test_client_init_failure_fails_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        target = sp.Target(label="t", base_url="https://a.com", model="m", api_key="k", timeout=5.0)

        def boom(_c: object) -> None:
            raise RuntimeError("bad key")

        monkeypatch.setattr(sp, "_ensure_client", boom)
        report = asyncio.run(sp.probe_target(target))
        assert report.supported is False
        assert report.results, "仍须给出四项结论"
        assert any("client init failed" in d for d in report.details)


class TestNoCliSurface:
    def test_no_argparse_in_script(self) -> None:
        """回归点 4：不提供 --provider（用户 2026-10-16 裁定「不需要 CLI」）。"""
        import argparse

        assert not any(isinstance(v, argparse.ArgumentParser) for v in vars(sp).values()), (
            "冒烟脚本不应引入 argparse"
        )

    def test_no_cli_entry_function(self) -> None:
        """唯一调用方式是 `python scripts/smoke_provider.py`，无第二入口。"""
        assert not hasattr(sp, "main"), "不应有独立 CLI main()——只有 __main__ 块"

    def test_checks_are_the_four_f802_items(self) -> None:
        assert [name for name, _ in sp.CHECKS] == [
            "structured_output",
            "tool_call",
            "parallel_tools",
            "streaming",
        ]
