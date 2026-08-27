"""store 槽语义一致性测试 —— StubStore vs SQLiteStore 必须行为对齐。

回归覆盖（2026-08-20 实现层验收发现）：
- F1: StubStore.supersede(observed_by="ai") 必须拒绝（契约红线：AI 不得静默改写）
- F2: count()/query() 只统计活跃记录（superseded_at 为空），两个实现语义一致
"""

import pytest

from gfcc_kernel.slots import SQLiteStore, StubStore


def _record(body: str = "test body", actor_sub: str = "tester-a") -> dict:
    return {"library": "issue", "body": body, "actor_sub": actor_sub,
            "observed_by": "human", "superseded_at": None}


class TestStubStore:
    def test_put_get_roundtrip(self):
        s = StubStore()
        rec = s.put(_record("牛奶"))
        assert s.get(rec["id"], actor_sub="tester-a")["body"] == "牛奶"

    def test_supersede_marks_old_creates_new(self):
        s = StubStore()
        rec = s.put(_record("旧内容"))
        new = s.supersede(rec["id"], {"body": "新内容"}, actor_sub="steward-1")
        assert new is not None
        assert new["id"] != rec["id"]
        assert new["body"] == "新内容"
        old = s.get(rec["id"], actor_sub="tester-a")
        assert old["superseded_at"] is not None  # 历史保留
        assert old["superseded_by"] == "steward-1"

    def test_f1_ai_cannot_supersede(self):
        # 契约红线：AI 不得静默改写（原 StubStore 不设防，已修）
        s = StubStore()
        rec = s.put(_record())
        with pytest.raises(ValueError, match="ai must not silently supersede"):
            s.supersede(rec["id"], {"body": "被 AI 改写"}, actor_sub="ai-agent", observed_by="ai")

    def test_f2_count_only_active(self):
        s = StubStore()
        r1 = s.put(_record("a"))
        s.put(_record("b"))
        assert s.count() == 2
        s.supersede(r1["id"], {"body": "a2"}, actor_sub="steward")
        # 旧 a 已替代不计入；新记录 a2 + b 活跃 → 2（与 SQLiteStore 对齐）
        assert s.count() == 2
        # 真正验证"已替代不计入"：直接标记一条被替代且无新记录
        r2 = s.put(_record("c"))
        s._records[r2["id"]]["superseded_at"] = "2026-08-20T00:00:00"
        assert s.count() == 2

    def test_f2_query_excludes_superseded(self):
        s = StubStore()
        r1 = s.put(_record("a"))
        s.put(_record("b"))
        s.supersede(r1["id"], {"body": "a2"}, actor_sub="steward")
        bodies = [r["body"] for r in s.query(actor_sub="tester-a")]
        assert "a" not in bodies
        assert "a2" in bodies  # 新记录可见
        assert "b" in bodies

    def test_query_requires_visibility(self):
        """收紧：无 circle_id 时 query 必须传 actor_sub（防全表泄漏）。"""
        s = StubStore()
        s.put(_record("a"))
        with pytest.raises(ValueError, match="actor_sub"):
            s.query()

    def test_get_requires_visibility(self):
        s = StubStore()
        rec = s.put(_record("a"))
        with pytest.raises(ValueError, match="actor_sub"):
            s.get(rec["id"])

    def test_query_isolated_by_actor(self):
        """Step1 验收核心：A 的记录，B 问不到（0 条）。"""
        s = StubStore()
        s.put(_record("A 的机密事项", actor_sub="tester-a"))
        s.put(_record("B 的日常", actor_sub="tester-b"))
        assert len(s.query(actor_sub="tester-a")) == 1
        assert s.query(actor_sub="tester-a")[0]["body"] == "A 的机密事项"
        # B 的视角看不到 A 的记录
        b_bodies = [r["body"] for r in s.query(actor_sub="tester-b")]
        assert "A 的机密事项" not in b_bodies
        assert b_bodies == ["B 的日常"]

    def test_get_hides_other_actor_record(self):
        """收紧：B 猜 A 的 id → 读不到 body（get 返回 None）。"""
        s = StubStore()
        rec = s.put(_record("A 的隐私", actor_sub="tester-a"))
        assert s.get(rec["id"], actor_sub="tester-a") is not None
        assert s.get(rec["id"], actor_sub="tester-b") is None

    def test_supersede_inherits_actor_sub(self):
        s = StubStore()
        rec = s.put(_record("旧", actor_sub="tester-a"))
        new = s.supersede(rec["id"], {"body": "新"}, actor_sub="tester-a")
        assert new["actor_sub"] == "tester-a"
        # 新记录只对 A 可见；B 仍看不到
        assert s.get(new["id"], actor_sub="tester-a") is not None
        assert s.get(new["id"], actor_sub="tester-b") is None


class TestSQLiteStore:
    def test_put_get_roundtrip(self):
        s = SQLiteStore(":memory:")
        rec = s.put(_record("牛奶"))
        assert s.get(rec["id"], actor_sub="tester-a")["body"] == "牛奶"
        s.close()

    def test_ai_cannot_supersede(self):
        s = SQLiteStore(":memory:")
        rec = s.put(_record())
        with pytest.raises(ValueError, match="ai must not silently supersede"):
            s.supersede(rec["id"], {"body": "被 AI 改写"}, actor_sub="ai-agent", observed_by="ai")
        s.close()

    def test_count_only_active(self):
        s = SQLiteStore(":memory:")
        r1 = s.put(_record("a"))
        s.put(_record("b"))
        assert s.count() == 2
        s.supersede(r1["id"], {"body": "a2"}, actor_sub="steward")
        # 旧 a 已替代不计入；新记录 a2 + b 活跃 → 2（与 StubStore 对齐）
        assert s.count() == 2
        # 真正验证"已替代不计入"：直接标记一条被替代且无新记录
        r2 = s.put(_record("c"))
        s._conn.execute(
            "UPDATE memory_records SET superseded_at='2026-08-20T00:00:00' WHERE id=?",
            (r2["id"],),
        )
        s._conn.commit()
        assert s.count() == 2
        s.close()

    def test_persistence_across_restart(self, tmp_path):
        # 重启不丢（Step1-2 验收基准）
        db = str(tmp_path / "memory.db")
        s1 = SQLiteStore(db)
        rec = s1.put(_record("重启后还在"))
        rid = rec["id"]
        s1.close()

        s2 = SQLiteStore(db)
        got = s2.get(rid, actor_sub="tester-a")
        assert got is not None
        assert got["body"] == "重启后还在"
        s2.close()

    def test_query_isolated_by_actor(self):
        """Step1 验收核心：SQLite 与 StubStore 行为一致。"""
        s = SQLiteStore(":memory:")
        s.put(_record("A 的机密事项", actor_sub="tester-a"))
        s.put(_record("B 的日常", actor_sub="tester-b"))
        assert len(s.query(actor_sub="tester-a")) == 1
        b_bodies = [r["body"] for r in s.query(actor_sub="tester-b")]
        assert "A 的机密事项" not in b_bodies
        assert b_bodies == ["B 的日常"]
        s.close()

    def test_get_hides_other_actor_record(self):
        s = SQLiteStore(":memory:")
        rec = s.put(_record("A 的隐私", actor_sub="tester-a"))
        assert s.get(rec["id"], actor_sub="tester-a") is not None
        assert s.get(rec["id"], actor_sub="tester-b") is None
        s.close()


class TestCrossImplementationParity:
    def test_supersede_semantics_parity(self):
        """同一操作序列，两个实现产生一致的可见状态。"""
        stub, lite = StubStore(), SQLiteStore(":memory:")
        sr = stub.put(_record("x"))
        lr = lite.put(_record("x"))
        stub.supersede(sr["id"], {"body": "y"}, actor_sub="u1")
        lite.supersede(lr["id"], {"body": "y"}, actor_sub="u1")
        assert stub.count() == lite.count()
        assert [r["body"] for r in stub.query(actor_sub="tester-a")] == \
               [r["body"] for r in lite.query(actor_sub="tester-a")] == ["y"]
        lite.close()

    def test_visibility_parity(self):
        """隔离语义一致：A 的记录对 B 在两个实现中同样不可见。"""
        stub, lite = StubStore(), SQLiteStore(":memory:")
        for s in (stub, lite):
            s.put(_record("私有", actor_sub="tester-a"))
        assert stub.query(actor_sub="tester-b") == []
        assert lite.query(actor_sub="tester-b") == []
        lite.close()
