"""根路径品牌门面 GET / —— 不动契约、不依赖业务接口。

验证：
- 返回 200 HTML，含品牌名/LOGO/四轴/五条判据/版本号。
- 静态资源（/static/brand-mark.png）可访问。
- 既有业务路由（/health、/circle/）不受影响。
"""

from fastapi.testclient import TestClient

from gfcc_kernel.app import app

client = TestClient(app)


class TestRootPage:
    def test_returns_html_200(self):
        r = client.get("/")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        # UTF-8（中文文案）
        assert "charset=utf-8" in r.headers["content-type"].lower() or "utf-8" in r.text

    def test_brand_mark_and_axes(self):
        body = client.get("/").text
        assert "格契" in body
        assert "GFCC" in body
        for axis in ("Genesis", "Fellowship", "Consensus", "Circle"):
            assert axis in body, f"missing axis: {axis}"
        # 四条五条判据
        for k in ("记得住", "协商得了", "贡献兑得现", "人往高处走", "AI 不抢戏"):
            assert k in body, f"missing principle: {k}"
        # 入口与运维
        assert "/circle/" in body
        assert "/health" in body
        # 版本号与契约对齐
        assert "v1.1.0" in body

    def test_uses_static_logo(self):
        body = client.get("/").text
        assert "/static/brand-mark.png" in body
        # srcset 提供 2x 高清
        assert "brand-mark@2x.png" in body


class TestStaticAssets:
    def test_brand_mark_png_served(self):
        r = client.get("/static/brand-mark.png")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert len(r.content) > 1000  # 不是空壳

    def test_brand_mark_2x_served(self):
        r = client.get("/static/brand-mark@2x.png")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"


class TestExistingRoutesUnaffected:
    """最小冒烟：品牌门页不应破坏既有契约端点。"""

    def test_health_still_ok(self):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["service"] == "gfcc_kernel"

    def test_circle_index_still_serves_html(self):
        # /circle/ 由 circle_web 提供；未带 token 时认证会 401，
        # 因此这里只验路由可达且返回 JSON/HTTP 响应（非 404）。
        r = client.get("/circle/")
        assert r.status_code != 404