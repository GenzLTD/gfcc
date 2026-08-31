"""W1 生态号纯函数测试 —— email_to_user_id_hash（Bolent 入驻预埋）。

标准向量与 docs/experiments/Bolent入驻预埋_Windows行动方案.md §3 钉死一致：
- alice@example.com        → ff8d9819fc0e12bf0d24892e45987e249a28dce836a85cad60e28eaaa8c6d976
- Alice@Example.COM        → 同上（大小写折叠）
- " alice@example.com "    → 同上（strip）
- bob@example.com          → 与 test_signal.py 的 HASH_B 同一表达式
- 空串 / 纯空白            → ValueError

算法纪律：HASH_A 与 test_signal.py 必须同一常量来源或同一表达式，禁止两套算法。
"""

import hashlib

import pytest

from gfcc_kernel.signal import email_to_user_id_hash

ALICE_HASH = "ff8d9819fc0e12bf0d24892e45987e249a28dce836a85cad60e28eaaa8c6d976"


def test_alice_standard_vector():
    """§3 第一行：alice@example.com 的标准向量必须逐字节相等。"""
    assert email_to_user_id_hash("alice@example.com") == ALICE_HASH


def test_case_folding():
    """§3 第二行：大小写折叠后与 alice 同值。"""
    assert email_to_user_id_hash("Alice@Example.COM") == ALICE_HASH


def test_strip_whitespace():
    """§3 第三行：首尾空白剥离后与 alice 同值。"""
    assert email_to_user_id_hash(" alice@example.com ") == ALICE_HASH


def test_output_is_64_lowercase_hex():
    """输出形状：64 位小写 hex（对齐信封 user_id_hash 的 pattern）。"""
    h = email_to_user_id_hash("someone@example.com")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_same_expression_as_test_signal():
    """与 test_signal.py 的 HASH_A 同一表达式：函数调用 ≡ 原始 sha256 表达式。"""
    assert email_to_user_id_hash("alice@example.com") == \
        hashlib.sha256("alice@example.com".encode("utf-8")).hexdigest()


def test_bob_matches_test_signal_hash_b():
    """bob 向量与 test_signal.py 的 HASH_B 同值（同一函数来源）。"""
    expected_b = hashlib.sha256("bob@example.com".encode("utf-8")).hexdigest()
    assert email_to_user_id_hash("bob@example.com") == expected_b


def test_empty_string_raises():
    with pytest.raises(ValueError):
        email_to_user_id_hash("")


def test_whitespace_only_raises():
    with pytest.raises(ValueError):
        email_to_user_id_hash("   \t  ")


def test_non_string_raises():
    with pytest.raises(ValueError):
        email_to_user_id_hash(None)  # type: ignore[arg-type]
