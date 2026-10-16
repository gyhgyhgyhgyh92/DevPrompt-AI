"""响应头与降级分流测试（M-11 / M-3）。

两件事：
- M-11：静态资源长缓存 + 入口 HTML 禁缓存 + 三个基础安全头
- M-3：内部补全端点（GET /preference）降级时带 X-Degraded，
  显式操作端点（GET /result）失败时必须 4xx 而非降级
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from devprompt_ai.interfaces.api.app import create_app

ASSETS_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


class TestCacheHeaders:
    def test_root_is_no_store(self, client: TestClient) -> None:
        """入口 HTML 必须每次回源，否则发版后用户仍加载旧 JS。"""
        cc = client.get("/").headers.get("cache-control", "")
        assert "no-store" in cc

    def test_index_html_is_no_store(self, client: TestClient) -> None:
        assert "no-store" in client.get("/index.html").headers.get("cache-control", "")

    @pytest.mark.skipif(not ASSETS_DIR.is_dir(), reason="需先pnpm build 生成 dist")
    def test_assets_are_immutably_cached(self, client: TestClient) -> None:
        """Vite 产物带内容哈希，可安全长期强缓存。"""
        assets = list((ASSETS_DIR / "assets").glob("*.js"))
        if not assets:
            pytest.skip("dist/assets 无 JS 文件")
        cc = client.get(f"/assets/{assets[0].name}").headers.get("cache-control", "")
        assert "immutable" in cc and "max-age=604800" in cc

    def test_api_responses_have_no_cache_directive(self, client: TestClient) -> None:
        """API 不应被缓存，但也不能误加 no-store 之外的指令。"""
        assert "immutable" not in client.get("/api/v1/health").headers.get("cache-control", "")


class TestSecurityHeaders:
    @pytest.mark.parametrize(
        ("header", "expected"),
        [
            ("x-content-type-options", "nosniff"),
            ("x-frame-options", "SAMEORIGIN"),
            ("referrer-policy", "no-referrer"),
        ],
    )
    def test_header_present(self, client: TestClient, header: str, expected: str) -> None:
        assert client.get("/").headers.get(header) == expected

    def test_no_csp_header(self, client: TestClient) -> None:
        """刻意不加 CSP：Vite 产物含内联样式，过严 CSP 会白屏。"""
        assert "content-security-policy" not in {k.lower() for k in client.get("/").headers}

    def test_api_also_gets_headers(self, client: TestClient) -> None:
        assert client.get("/api/v1/health").headers.get("x-content-type-options") == "nosniff"


class TestM3DegradationSplit:
    """M-3 核心契约：内部补全降级、显式操作报错。两者不可弄反。"""

    async def test_preference_read_failure_degrades_with_header(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """页面挂载时自动读偏好——store 读失败应回落中性值 + 标记降级，不应 500。

        注入点选`SQLitePreferenceStore.load`（更内层、更贴近真实的降级场景：
        DB 读失败），而不是 service 方法本身。
        """
        from devprompt_ai.memory.preference_store import SQLitePreferenceStore

        async def failing(self: object, user_id: str) -> dict[str, float]:
            raise RuntimeError("模拟 DB 读失败")

        monkeypatch.setattr(SQLitePreferenceStore, "load", failing)

        resp = client.get("/api/v1/preference")
        assert resp.status_code == 200, "内部补全不得因读取失败而让页面打不开"
        assert resp.headers.get("X-Degraded") == "preference_read_fallback"
        data = resp.json()["data"]
        assert data["detail_level"] == 0.5, "应回落中性值"

    def test_normal_preference_read_has_no_degraded_header(self, client: TestClient) -> None:
        resp = client.get("/api/v1/preference")
        assert resp.status_code == 200
        assert "X-Degraded" not in resp.headers

    def test_result_missing_session_stays_4xx(self, client: TestClient) -> None:
        """显式操作失败必须 4xx——降级成空快照会让前端误判为「会话无内容」。"""
        resp = client.get("/api/v1/result/no-such-session")
        assert resp.status_code >= 400
        assert "X-Degraded" not in resp.headers
        body = resp.json()
        assert body["code"] == 6003
        assert "重新选择" in body["message"], "文案要说清用户下一步该做什么"
