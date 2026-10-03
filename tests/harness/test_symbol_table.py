"""SymbolTableProvider 缓存行为测试（Fake runner，无真实 ctags）。"""

from devprompt_ai.harness.process import SymbolTableProvider

_CTAGS_OUT = '{"_type":"tag","name":"App","path":"src/App.tsx","line":1,"kind":"function"}\n'


class FakeRunner:
    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.calls = 0
        self.calls_args: list[list[str]] = []

    async def run(self, args: list[str], **kw: object) -> str:
        self.calls += 1
        self.calls_args.append(args)
        return self.raw


async def test_first_call_miss_then_hit() -> None:
    runner = FakeRunner(_CTAGS_OUT)
    provider = SymbolTableProvider(runner, ttl_seconds=3600.0)
    r1 = await provider.get("C:/proj")
    assert r1.cache_hit is False
    assert r1.symbols[0].name == "App"
    r2 = await provider.get("C:/proj")
    assert r2.cache_hit is True  # TTL 内命中
    assert runner.calls == 1  # 第二次未再调 ctags


async def test_mtime_change_invalidates() -> None:
    provider = SymbolTableProvider(FakeRunner(_CTAGS_OUT), ttl_seconds=3600.0)
    await provider.get("C:/proj")
    provider.mtime_digest_override = "changed"  # 模拟文件变更
    r = await provider.get("C:/proj")
    assert r.cache_hit is False  # MUST-14：mtime 变化必须失效


async def test_ttl_expiry() -> None:
    provider = SymbolTableProvider(FakeRunner(_CTAGS_OUT), ttl_seconds=0.0)
    await provider.get("C:/proj")
    r2 = await provider.get("C:/proj")
    assert r2.cache_hit is False  # TTL=0 立即过期


async def test_different_root_is_cache_miss() -> None:
    runner = FakeRunner(_CTAGS_OUT)
    provider = SymbolTableProvider(runner, ttl_seconds=3600.0)
    await provider.get("C:/proj")
    await provider.get("C:/other")  # 项目路径是缓存键因子（MUST-14），不得串缓存
    assert runner.calls == 2


async def test_excludes_passed_to_ctags() -> None:
    runner = FakeRunner(_CTAGS_OUT)
    provider = SymbolTableProvider(runner, ttl_seconds=3600.0)
    await provider.get("C:/proj")
    assert "--exclude=node_modules" in runner.calls_args[0]
    assert "--exclude=__pycache__" in runner.calls_args[0]
