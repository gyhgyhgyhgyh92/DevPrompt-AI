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
    # src 修复随附：.tsx 映射与 Markdown 排除必须由 src 下发，脚本层不再补偿
    assert "--map-TypeScript=+.tsx" in runner.calls_args[0]
    assert "--languages=-Markdown" in runner.calls_args[0]


async def test_symbols_paths_normalized_to_repo_relative() -> None:
    # ctags 输出含仓库根前缀（绝对 root），Provider 必须归一为仓库相对 POSIX 路径
    raw = (
        '{"_type":"tag","name":"App","path":"C:/proj/src/App.tsx","line":1,"kind":"function"}\n'
        '{"_type":"tag","name":"B","path":"C:/proj/src/ui/b.tsx","line":2,"kind":"function"}\n'
    )
    provider = SymbolTableProvider(FakeRunner(raw), ttl_seconds=3600.0)
    r = await provider.get("C:/proj")
    assert [s.path for s in r.symbols] == ["src/App.tsx", "src/ui/b.tsx"]


class RejectSignatureRunner(FakeRunner):
    """模拟不认 `{signature}` 字段的老版 ctags：带该字段直接抛错。"""

    async def run(self, args: list[str], **kw: object) -> str:
        if any("{signature}" in arg for arg in args):
            self.calls += 1
            self.calls_args.append(args)
            raise RuntimeError("ctags: Unknown field name: signature")
        return await super().run(args, **kw)


async def test_signature_capability_probed_once() -> None:
    """老版 ctags 只在首次失败一次；之后直接不带签名，不再白跑失败调用（2026-11-07）。"""
    runner = RejectSignatureRunner(_CTAGS_OUT)
    provider = SymbolTableProvider(runner, ttl_seconds=3600.0)

    await provider.get("C:/proj")
    assert len(runner.calls_args) == 2  # 带签名失败 → 去签名重试成功

    provider.mtime_digest_override = "changed"  # 强制缓存失效，触发第二次真实调用
    await provider.get("C:/proj")
    assert len(runner.calls_args) == 3  # 只多一次，且不带签名
    assert all("{signature}" not in arg for arg in runner.calls_args[-1])


async def test_relative_root_paths_normalized() -> None:
    # root 为相对路径（如 eval/recall/mock-x）时同样归一
    raw = (
        '{"_type":"tag","name":"App","path":"eval/recall/mock-x/src/App.tsx",'
        '"line":1,"kind":"function"}\n'
    )
    provider = SymbolTableProvider(FakeRunner(raw), ttl_seconds=3600.0)
    r = await provider.get("eval/recall/mock-x")
    assert r.symbols[0].path == "src/App.tsx"
