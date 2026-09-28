"""test_security.py — 上传硬化 + PII/凭证脱敏 + 限流 (维度 6.2/7.2/15)."""
from __future__ import annotations

import time

import pytest

from services import security as sec


# ---- 路径穿越防护 ----
def test_safe_filename_strips_traversal():
    assert sec.safe_filename("../../etc/passwd") == "passwd"     # 只取 basename
    assert ".." not in sec.safe_filename("../../secret.txt")
    assert "/" not in sec.safe_filename("../../etc/passwd")
    assert sec.safe_filename("C:\\Windows\\system32\\x.txt").endswith("x.txt")
    assert sec.safe_filename(None) == "upload.bin"
    assert sec.safe_filename("") == "upload.bin"


def test_safe_filename_keeps_normal_and_cjk():
    assert sec.safe_filename("draw_v1.STEP") == "draw_v1.STEP"
    assert sec.safe_filename("图纸.STEP") == "图纸.STEP"


# ---- 大小上限 ----
def test_size_guard():
    sec.size_guard(1024, limit=2048)               # ok 不抛
    with pytest.raises(ValueError):
        sec.size_guard(3000, limit=2048)


# ---- PII / 凭证脱敏 ----
def test_redact_credentials():
    t = "key sk-abc123456789 and token ghp_abcdefghij1234567890"
    r = sec.redact(t)
    assert "sk-abc123456789" not in r and "<REDACTED_API_KEY>" in r
    assert "ghp_abcdefghij1234567890" not in r


def test_redact_email_and_phone():
    r = sec.redact("contact alice@northwind.com or 13800138000")
    assert "alice@northwind.com" not in r and "<REDACTED_EMAIL>" in r
    assert "13800138000" not in r and "<REDACTED_PHONE>" in r


def test_redact_password_and_bearer():
    r = sec.redact("password=hunter2 Bearer abcdefgh12345678")
    assert "hunter2" not in r
    assert "<REDACTED_BEARER>" in r


def test_redact_private_key_block():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEabc\n-----END RSA PRIVATE KEY-----"
    assert "<REDACTED_PRIVATE_KEY>" in sec.redact(pem)


def test_redact_non_string_passthrough():
    assert sec.redact(123) == 123
    assert sec.redact(None) is None


def test_redact_dict_only_target_keys():
    d = {"email": "a@b.com", "note": "keep a@b.com here"}
    r = sec.redact_dict(d)
    assert r["email"] == "<REDACTED_EMAIL>"
    assert r["note"] == "keep a@b.com here"        # 非目标键不动


# ---- 限流 ----
def test_rate_limiter_blocks_after_capacity():
    rl = sec.RateLimiter(capacity=3, refill_rate=0.0)
    assert [rl.allow("u") for _ in range(3)] == [True, True, True]
    assert rl.allow("u") is False                    # 第 4 次被限


def test_rate_limiter_refills():
    rl = sec.RateLimiter(capacity=1, refill_rate=50.0)   # 50 tokens/s
    assert rl.allow("u") is True
    assert rl.allow("u") is False
    time.sleep(0.05)                                  # 补充 ~2.5 tokens
    assert rl.allow("u") is True


def test_rate_limiter_per_key_isolation():
    rl = sec.RateLimiter(capacity=1, refill_rate=0.0)
    assert rl.allow("a") is True
    assert rl.allow("a") is False
    assert rl.allow("b") is True                      # 不同 key 独立


def test_rate_limiter_reset():
    rl = sec.RateLimiter(capacity=1, refill_rate=0.0)
    rl.allow("u"); assert rl.allow("u") is False
    rl.reset("u")
    assert rl.allow("u") is True
