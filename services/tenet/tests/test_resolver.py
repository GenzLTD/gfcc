"""Tenet resolver 模块测试（pytest）。"""

import os
import sys
from pathlib import Path

from tenet.resolver import (
    StaticResourceLocator,
    StaticServiceLocator,
    TtlCachedLocator,
    init_resolver,
)


def test_static_service_locator():
    loc = StaticServiceLocator({"knowledge-api": "http://127.0.0.1:8000"})
    assert loc.locate("knowledge-api") == "http://127.0.0.1:8000"
    assert loc.locate("KNOWLEDGE-API") == "http://127.0.0.1:8000"  # 大小写不敏感
    assert loc.locate("nope") is None


def test_env_override_service():
    os.environ["TENET_SERVICES_CHROMA"] = "http://127.0.0.1:8001"
    try:
        loc = StaticServiceLocator({})
        assert loc.locate("chroma") == "http://127.0.0.1:8001"
    finally:
        os.environ.pop("TENET_SERVICES_CHROMA", None)


def test_resource_platform_branch():
    mapping = {
        "vault.json": {
            "win32": "E:/Data/vault.json",
            "darwin": "/Users/me/Data/vault.json",
            "linux": "/srv/data/vault.json",
            "any": "/tmp/vault.json",
        }
    }
    loc = StaticResourceLocator(mapping)
    resolved = loc.resolve("vault.json")
    expected = mapping["vault.json"].get(sys.platform) or mapping["vault.json"]["any"]
    assert resolved == Path(expected)  # Path 比较会自动规范化分隔符，双平台通用


def test_resource_env_placeholder():
    os.environ["MY_DATA_DIR"] = "C:/custom/data"
    try:
        loc = StaticResourceLocator({"chroma": "${MY_DATA_DIR}/merged_chroma"})
        assert loc.resolve("chroma") == Path("C:/custom/data/merged_chroma")
    finally:
        os.environ.pop("MY_DATA_DIR", None)


def test_resource_default_relative():
    loc = StaticResourceLocator({})
    assert loc.resolve("db") == Path("data") / "db"  # 未配置回退相对路径


def test_env_resource_fallback():
    os.environ["TENET_RESOURCE_VAULT_JSON"] = "E:/fallback/vault.json"
    try:
        from tenet.resolver.resource_locator import EnvResourceLocator

        assert EnvResourceLocator().resolve("vault.json") == Path("E:/fallback/vault.json")
    finally:
        os.environ.pop("TENET_RESOURCE_VAULT_JSON", None)


def test_ttl_cache():
    calls = {"n": 0}

    class CountingLocator:
        def locate(self, name):
            calls["n"] += 1
            return "http://x:1"

    loc = TtlCachedLocator(CountingLocator(), ttl_seconds=60)
    assert loc.locate("a") == "http://x:1"
    assert loc.locate("a") == "http://x:1"
    assert calls["n"] == 1  # 第二次命中缓存


def test_init_resolver_static():
    ctx = init_resolver(services={"search": "http://127.0.0.1:8010"})
    assert ctx["service_locator"].locate("search") == "http://127.0.0.1:8010"


def test_load_resource_config_json(tmp_path):
    cfg = tmp_path / "resources.json"
    cfg.write_text(
        '{"chinese-poetry": {"win32": "E:/FiveBlessings/chinese-poetry",'
        ' "darwin": "/Users/me/FiveBlessings/chinese-poetry"},'
        ' "chroma": "${TATHA_ROOT}/.data/chroma/poetry_full"}',
        encoding="utf-8",
    )
    ctx = init_resolver(resources_path=cfg)
    loc = ctx["resource_locator"]
    cp = loc.resolve("chinese-poetry")
    assert cp == Path("E:/FiveBlessings/chinese-poetry" if sys.platform == "win32"
                      else "/Users/me/FiveBlessings/chinese-poetry")
    os.environ["TATHA_ROOT"] = "D:/proj/Tatha"
    try:
        assert loc.resolve("chroma") == Path("D:/proj/Tatha/.data/chroma/poetry_full")
    finally:
        os.environ.pop("TATHA_ROOT", None)


def test_load_resource_config_toml(tmp_path):
    import pytest

    pytest.importorskip("tomllib")  # Python 3.11+；3.10 自动跳过
    cfg = tmp_path / "resources.toml"
    cfg.write_text(
        '["chinese-poetry"]\nwin32 = "E:/Data/chinese-poetry"\n',
        encoding="utf-8",
    )
    ctx = init_resolver(resources_path=cfg)
    assert ctx["resource_locator"].resolve("chinese-poetry") == Path("E:/Data/chinese-poetry")


def test_inline_resources_override_file(tmp_path):
    cfg = tmp_path / "resources.json"
    cfg.write_text('{"db": {"any": "E:/file/db"}}', encoding="utf-8")
    ctx = init_resolver(resources_path=cfg, resources={"db": {"any": "E:/inline/db"}})
    assert ctx["resource_locator"].resolve("db") == Path("E:/inline/db")


def test_resource_config_missing_file(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        init_resolver(resources_path=tmp_path / "nope.json")
