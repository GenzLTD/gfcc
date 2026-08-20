"""
E2E 测试：订阅页按地区展示价格。需先启动主仓 API（uv run uvicorn tatha.api.app:app --host 127.0.0.1 --port 5210）。
若 5210 不可达则跳过 E2E。
"""
import socket

import pytest

E2E_BASE_URL = "http://127.0.0.1:5210"


def _server_reachable(host: str = "127.0.0.1", port: int = 5210) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def base_url():
    """Playwright base_url；若服务未启动则跳过 E2E。"""
    if not _server_reachable():
        pytest.skip("E2E 需要先启动 API: uv run uvicorn tatha.api.app:app --host 127.0.0.1 --port 5210")
    return E2E_BASE_URL
