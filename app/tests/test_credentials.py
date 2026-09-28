"""test_credentials.py — v3.0 #40 credentials 模块单测.

7 条覆盖:
  1) save→load 往返 (Fernet 解密正确)
  2) mask_secret 行为 (head/tail + 短串)
  3) delete_credentials 真删除 + 二次删返回 False
  4) list_services 列出已存服务
  5) status() 含 fernet_available
  6) 凭据缺参返回 ok=False
  7) _load_all 容错 (损坏 JSON 不抛异常)

凭代码核对: 严格调用 services.credentials 现有函数, 不发明.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import credentials as cred_mod


@pytest.fixture
def tmp_cred_file(tmp_path, monkeypatch):
    """重定向 CRED_FILE 到 tmp_path, 隔离本机 credentials.json."""
    fake = tmp_path / "credentials.json"
    monkeypatch.setattr(cred_mod, "CRED_FILE", fake)
    return fake


# ---------------- 1) save + load 往返 ----------------
def test_save_load_roundtrip(tmp_cred_file):
    """save_credentials → load_credentials 应能解密还原 password."""
    r = cred_mod.save_credentials("gmail", "alice@gmail.com", "abcd-efgh-ijkl-mnop")
    assert r["ok"] is True
    assert r["service"] == "gmail"
    assert r["account"] == "alice@gmail.com"
    assert r["masked"] == "ab***************op"  # 19 字符 → head=2 tail=2 中间 15
    loaded = cred_mod.load_credentials("gmail")
    assert loaded is not None
    assert loaded["service"] == "gmail"
    assert loaded["account"] == "alice@gmail.com"
    assert loaded["password"] == "abcd-efgh-ijkl-mnop"
    # cipher 字段应标注 (fernet 或 base64 降级)
    assert loaded["cipher"] in ("fernet-aes128-cbc-hmac-sha256", "base64-insecure")


# ---------------- 2) mask_secret ----------------
def test_mask_secret_long():
    """长密码 → 保留头尾, 中间变 *."""
    assert cred_mod.mask_secret("abcdefghij") == "ab******ij"


def test_mask_secret_short():
    """短串 (≤head+tail) → 全部 *."""
    assert cred_mod.mask_secret("abc") == "***"
    assert cred_mod.mask_secret("") == ""


# ---------------- 3) delete ----------------
def test_delete_credentials(tmp_cred_file):
    """save 后 delete → 删成功; 二次 delete → False."""
    cred_mod.save_credentials("gmail", "x@y.com", "pw1234")
    assert cred_mod.delete_credentials("gmail") is True
    assert cred_mod.load_credentials("gmail") is None
    assert cred_mod.delete_credentials("gmail") is False  # 已删


# ---------------- 4) list_services ----------------
def test_list_services(tmp_cred_file):
    """存 2 个 service → list 返回 2 条 (含 masked + cipher)."""
    cred_mod.save_credentials("gmail", "a@b.com", "secret1")
    cred_mod.save_credentials("imap_other", "c@d.com", "secret2-long")
    items = cred_mod.list_services()
    assert len(items) == 2
    svcs = {x["service"] for x in items}
    assert svcs == {"gmail", "imap_other"}
    for it in items:
        assert "account" in it and "masked" in it and "cipher" in it


# ---------------- 5) status ----------------
def test_status_contains_fernet(tmp_cred_file):
    """status() 报告 cred_file + fernet_available."""
    s = cred_mod.status()
    assert "cred_file" in s
    assert s["cred_file"] == str(tmp_cred_file)
    assert "fernet_available" in s
    assert isinstance(s["fernet_available"], bool)
    assert s["services"] == []  # 还没存


# ---------------- 6) 缺参 ----------------
def test_save_missing_arg(tmp_cred_file):
    """空 service/account/password → ok=False, 不抛异常."""
    assert cred_mod.save_credentials("", "a@b.com", "pw")["ok"] is False
    assert cred_mod.save_credentials("gmail", "", "pw")["ok"] is False
    assert cred_mod.save_credentials("gmail", "a@b.com", "")["ok"] is False


# ---------------- 7) _load_all 容错 ----------------
def test_load_all_corrupted_json(tmp_cred_file):
    """写入损坏 JSON → _load_all 不抛异常, 返回空 dict 结构."""
    tmp_cred_file.write_text("{not valid json,,,", encoding="utf-8")
    data = cred_mod._load_all()
    assert data == {"version": 1, "services": {}}