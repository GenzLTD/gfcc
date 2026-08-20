"""端口解析与调度测试 —— 关键词规则兜底（CI 无 Ollama，只测确定性路径）。

_parse_port_keywords 是 CI 基准（dispatcher 文档明确约定）。
"""

from gfcc_kernel.dispatcher import parse_port, parse_then_dispatch
from gfcc_kernel.envelope import AskRequest
from gfcc_kernel.registry import PortRegistry


class TestParsePort:
    def test_port_hint_wins(self):
        port, conf = parse_port("你好呀", port_hint="memory")
        assert port == "memory"
        assert conf == 1.0

    def test_port_hint_unknown(self):
        port, conf = parse_port("围坐安排一下", port_hint="unknown")
        assert port == "unknown"
        assert conf == 0.0

    def test_invalid_port_hint_ignored(self):
        port, _ = parse_port("记住买牛奶", port_hint="not_a_port")
        assert port == "memory"  # 落回关键词规则

    def test_keyword_memory(self):
        port, _ = parse_port("记住明天要开会")
        assert port == "memory"

    def test_keyword_circle(self):
        port, _ = parse_port("帮我安排一次围坐")
        assert port == "circle"

    def test_keyword_consensus(self):
        port, _ = parse_port("表决一下这个提议")
        assert port == "consensus"

    def test_keyword_contribution(self):
        port, _ = parse_port("帮我认定这个贡献")
        assert port == "contribution"

    def test_keyword_identity(self):
        port, _ = parse_port("更新我的身份画像")
        assert port == "identity"

    def test_chitchat_unknown(self):
        port, conf = parse_port("你好")
        assert port == "unknown"
        assert conf == 0.0


class TestParseThenDispatch:
    def _ctx(self):
        return PortRegistry().build_context(
            session_id="s-test", circle_id=None,
            dialog_mode="collaboration", policy=None, llm=None,
        )

    def test_unknown_returns_suggestions(self):
        req = AskRequest(message="你好")
        resp = parse_then_dispatch(req, self._ctx())
        assert resp.port == "unknown"
        assert resp.status == "unknown"
        assert resp.result.receipts == []
        assert resp.suggestions  # 有引导建议

    def test_memory_write_via_port_hint(self):
        req = AskRequest(message="记住买牛奶", context={"port_hint": "memory"})
        resp = parse_then_dispatch(req, self._ctx())
        assert resp.port == "memory"
        assert resp.status == "ok"
        assert resp.result.receipts[0].port == "memory"
        assert resp.result.receipts[0].id  # 写操作返回 id

    def test_circle_listing(self):
        req = AskRequest(message="看看有哪些围坐圈子", context={"port_hint": "circle"})
        resp = parse_then_dispatch(req, self._ctx())
        assert resp.port == "circle"
        assert resp.status == "ok"

    def test_contribution_listing(self):
        req = AskRequest(message="贡献记录", context={"port_hint": "contribution"})
        resp = parse_then_dispatch(req, self._ctx())
        assert resp.port == "contribution"
        assert resp.status == "ok"
