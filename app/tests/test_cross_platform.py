"""tests/test_cross_platform.py — D-P1 跨平台加固.

铁律: data-stays-local 依赖 credentials 在所有平台可写.
Windows 有 os.O_BINARY, POSIX (Linux/macOS) 没有 → 直接引用会 AttributeError.
本测覆盖凭据保存路径在缺失 O_BINARY 时仍工作 (getattr 回退 0).
"""
from __future__ import annotations

import os

import pytest

from services import credentials as cred_mod


def test_save_credentials_without_o_binary(tmp_path, monkeypatch):
    """模拟 POSIX: 删除 os.O_BINARY → save/load 仍应成功 (回退 0)."""
    fake = tmp_path / "credentials.json"
    monkeypatch.setattr(cred_mod, "CRED_FILE", fake)
    monkeypatch.delattr(os, "O_BINARY", raising=False)
    assert not hasattr(os, "O_BINARY")
    r = cred_mod.save_credentials("gmail", "a@b.com", "pw12345678")
    assert r["ok"] is True
    loaded = cred_mod.load_credentials("gmail")
    assert loaded is not None
    assert loaded["password"] == "pw12345678"


def test_save_credentials_with_o_binary(tmp_path, monkeypatch):
    """Windows 原路径: O_BINARY 存在时照常工作 (回归保护)."""
    fake = tmp_path / "credentials.json"
    monkeypatch.setattr(cred_mod, "CRED_FILE", fake)
    r = cred_mod.save_credentials("gmail", "win@b.com", "pw-abcdefgh")
    assert r["ok"] is True
    assert cred_mod.load_credentials("gmail")["password"] == "pw-abcdefgh"
