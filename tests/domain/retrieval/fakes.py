"""domain/retrieval 测试共用 Fake（无真实进程/文件系统，MUST-06 验证标准）。"""

from devprompt_ai.domain.retrieval.ports import CommandRunner, FileReader


class FakeCommandRunner(CommandRunner):
    """按「命令首词 + --route-key」路由到预置输出的假 runner。

    未命中路由时返回空串（等价 rg 无匹配、退出码 1 的语义）。
    """

    def __init__(self, routes: dict[tuple[str, str], str]) -> None:
        self._routes = routes
        self.calls: list[list[str]] = []
        self.cwds: list[str | None] = []

    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 10.0,
        allowed_exit_codes: frozenset[int] = frozenset({0}),
        cwd: str | None = None,
    ) -> str:
        self.calls.append(args)
        self.cwds.append(cwd)
        word = args[0] if args else ""
        key = next((a.split("=", 1)[1] for a in args if a.startswith("--route-key=")), "")
        return self._routes.get((word, key), "")


class FakeFileReader(FileReader):
    def __init__(self, files: dict[str, str], existing: set[str] | None = None) -> None:
        self._files = files
        self._existing = existing if existing is not None else set(files)

    async def read(self, path: str) -> str:
        return self._files[path]

    async def exists(self, path: str) -> bool:
        return path in self._existing
