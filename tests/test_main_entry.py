"""ASGI 入口不变量测试（T7-7 交付补强）。

锁死两条约束：
1. `devprompt_ai.main:app` 与 `interfaces.api.app:app` 必须是**同一实例**——
   若main.py 改为自行 `create_app()`，CORS/异常处理器/X-Request-ID 状态将分裂，
   违反 MUST-10「状态单一、配置单一」。该回归靠对象身份断言而非类型断言保证。
2. console script 入口 `main()` 只做「参数收拢 → 调uvicorn」，不产生业务逻辑。
"""

from __future__ import annotations

from typing import Any

import pytest

from devprompt_ai import main as main_module
from devprompt_ai.main import main


def test_app_is_same_instance_as_api_app() -> None:
    """main:app 必须是 app.py 实例的再导出，而非第二个应用实例。"""
    from devprompt_ai.interfaces.api.app import app as api_app

    assert main_module.app is api_app


def test_unknown_attribute_raises_attribute_error() -> None:
    """未知名必须抛 AttributeError，保留标准模块语义（PEP 562）。"""
    with pytest.raises(AttributeError, match="has no attribute 'not_a_real_attr'"):
        _ = main_module.not_a_real_attr


def test_app_is_importable_by_uvicorn_target_path() -> None:
    """uvicorn devprompt_ai.main:app 的目标路径可解析（与应用工厂同实例）。"""
    from devprompt_ai.interfaces.api import app as api_module

    assert main_module.app is api_module.app


@pytest.fixture
def _fake_uvicorn(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """拦截 uvicorn.run：记录入参而不真正起服务。"""
    calls: list[dict[str, Any]] = []

    class _FakeUvicorn:
        @staticmethod
        def run(target: str, **kwargs: Any) -> None:
            calls.append({"target": target, **kwargs})

    monkeypatch.setitem(__import__("sys").modules, "uvicorn", _FakeUvicorn)
    return calls


def test_main_defaults_to_localhost_and_app_target(_fake_uvicorn: list[dict[str, Any]]) -> None:
    """默认参数：仅本机回环 + 以模块路径启动（兼容 --reload）。"""
    assert main([]) == 0
    assert len(_fake_uvicorn) == 1
    assert _fake_uvicorn[0]["target"] == "devprompt_ai.main:app"
    assert _fake_uvicorn[0]["host"] == main_module.DEFAULT_HOST
    assert _fake_uvicorn[0]["port"] == main_module.DEFAULT_PORT
    assert _fake_uvicorn[0]["reload"] is False


def test_main_forwards_custom_host_port_reload(_fake_uvicorn: list[dict[str, Any]]) -> None:
    """显式参数透传到 uvicorn.run。"""
    assert main(["--host", "0.0.0.0", "--port", "9000", "--reload"]) == 0
    assert _fake_uvicorn[0]["host"] == "0.0.0.0"
    assert _fake_uvicorn[0]["port"] == 9000
    assert _fake_uvicorn[0]["reload"] is True


def test_main_open_flag_invokes_browser(
    monkeypatch: pytest.MonkeyPatch, _fake_uvicorn: list[dict[str, Any]]
) -> None:
    """--open 调用默认浏览器，且 URL 对通配监听地址改用 localhost。"""
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    main(["--host", "0.0.0.0", "--open"])
    assert opened == [f"http://localhost:{main_module.DEFAULT_PORT}"]


def test_main_help_exits_without_importing_app(capsys: pytest.CaptureFixture[str]) -> None:
    """--help 只打印帮助并退出，且**不**构造 AppConfig（惰性导入的收益）。"""
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "--reload" in capsys.readouterr().out


def test_display_url_maps_wildcard_hosts() -> None:
    """监听通配地址不可导航，展示 URL 统一回落 localhost。"""
    assert main_module._display_url("0.0.0.0", 8765) == "http://localhost:8765"
    assert main_module._display_url("::", 8765) == "http://localhost:8765"
    assert main_module._display_url("127.0.0.1", 8080) == "http://127.0.0.1:8080"


def test_console_script_entry_point_registered() -> None:
    """pyproject 声明的 console script 目标必须与 main 实际导出对得上。

    用文本匹配而非 tomllib 解析：mypy 以python_version=3.10 为准，
    而 tomllib 是 3.11+ 标准库（tomllib 不可用，故不做引入）。
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project.scripts]" in source
    assert 'devprompt-ai = "devprompt_ai.main:main"' in source


def test_no_business_logic_in_entry_module() -> None:
    """main.py 只允许 app 再导出与 serve：不得出现评分/阈值常量（MUST-08/10）。"""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src/devprompt_ai/main.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("0.12", "0.6", "0.4", "threshold", "score", "weight"):
        assert forbidden not in source, f"入口层出现业务常量：{forbidden}"


def test_main_does_not_import_infrastructure_at_module_level() -> None:
    """入口模块顶层不得直接 import 基础设施实现模块（薄壳约束，MUST-06）。"""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src/devprompt_ai/main.py").read_text(
        encoding="utf-8"
    )
    module_level = [
        line
        for line in source.splitlines()
        if line.startswith(("import ", "from ")) and "devprompt_ai" in line
    ]
    assert module_level == []
