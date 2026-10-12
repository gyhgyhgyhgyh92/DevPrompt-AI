"""测试全局夹具：本地设置源默认禁用（AppConfig 加载链隔离，T6-11）。

MUST-19 修订后 AppConfig 会读 settings.json + app_settings 表（默认 ~/.devprompt-ai/）；
测试若不隔离会受真实用户配置污染。需要设置源的用例以 monkeypatch.setenv 显式指向 tmp 路径。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _disable_local_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVPROMPT_SETTINGS_FILE", "")
    monkeypatch.setenv("DEVPROMPT_SETTINGS_DB", "")


@pytest.fixture(autouse=True)
def _reset_telemetry() -> Iterator[None]:
    """遥测开关是进程级全局态（observability.logging），用例间必须复位。"""
    from devprompt_ai.observability.logging import set_telemetry

    set_telemetry(True)
    yield
    set_telemetry(True)
