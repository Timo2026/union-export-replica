"""test_file_intake.py — 全模态上传解析 + C1 ZIP ingestion (任务 #27).

C1 覆盖 (杰沃 -drawings.zip 场景):
  - GBK 文件名: 真实 zip 里 flag_bits 无 0x800, 名字是 GBK 原始字节 → 必须 cp437→gbk 解码
  - 嵌套 zip 递归解包 (深度上限)
  - zip slip / 绝对路径穿越 → 拒绝落盘, 显式标注
  - 解出的每个文件带 classify kind, 交由上层逐模态解析

fixture 用手工字节构造 zip: Python zipfile 对非 ASCII 名强制 UTF-8 flag,
无法产出真实世界的 GBK zip, 故绕开 zipfile 写库。
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Dict, List, Tuple

import pytest


def _make_zip(entries: List[Tuple[bytes, bytes]]) -> bytes:
    """构造 store-only zip; entries = [(raw_name_bytes, data_bytes)]."""
    local_parts: List[bytes] = []
    central_parts: List[bytes] = []
    offset = 0
    for name, data in entries:
        crc = zlib.crc32(data) & 0xFFFFFFFF
        lh = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0,
                         crc, len(data), len(data), len(name), 0) + name
        local_parts.append(lh + data)
        ch = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50,
                         20, 20, 0, 0, 0, 0,       # 6H: madeby/need/flags/method/time/date
                         crc, len(data), len(data),  # 3I: crc/csize/usize
                         len(name), 0, 0, 0, 0,    # 5H: namelen/extra/comment/disk/intattr
                         0, offset) + name         # 2I: extattr/localhdr offset
        central_parts.append(ch)
        offset += len(lh) + len(data)
    local_blob = b"".join(local_parts)
    central_blob = b"".join(central_parts)
    eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0,
                       len(entries), len(entries),
                       len(central_blob), len(local_blob), 0)
    return local_blob + central_blob + eocd


@pytest.fixture
def gbk_zip(tmp_path: Path) -> Path:
    p = tmp_path / "drawings.zip"
    inner = _make_zip([("内部/readme.txt".encode("gbk"), b"inner text")])
    p.write_bytes(_make_zip([
        ("外壳说明.txt".encode("gbk"), b"top text"),
        ("drawings/图纸_A.step".encode("gbk"), b"ISO-10303-21;"),
        (b"nested.zip", inner),
    ]))
    return p


@pytest.fixture
def slip_zip(tmp_path: Path) -> Path:
    p = tmp_path / "slip.zip"
    p.write_bytes(_make_zip([
        (b"good.txt", b"ok"),
        (b"../escape.txt", b"BAD"),
        (b"/abs_escape.txt", b"BAD"),
        (b"ok/sub/../also_good.txt", b"fine"),
    ]))
    return p


# ---------- decode_zip_name ----------
def test_decode_zip_name_gbk_bytes():
    from services.file_intake import decode_zip_name
    raw = "图纸_A.step".encode("gbk")
    assert decode_zip_name(raw, utf8_flag=False) == "图纸_A.step"


def test_decode_zip_name_utf8_flag_passthrough():
    from services.file_intake import decode_zip_name
    raw = "外壳说明.txt".encode("utf-8")
    assert decode_zip_name(raw, utf8_flag=True) == "外壳说明.txt"


def test_decode_zip_name_gbk_fail_falls_back_cp437():
    """非法 GBK 序列 → 不抛异常, cp437 兜底 (显式可解释)."""
    from services.file_intake import decode_zip_name
    raw = b"\x80\x81notes.txt"
    out = decode_zip_name(raw, utf8_flag=False)
    assert out.endswith("notes.txt")


# ---------- extract_zip: GBK 名 + 嵌套 ----------
def test_extract_zip_decodes_gbk_names_and_nests(gbk_zip: Path, tmp_path: Path):
    from services.file_intake import extract_zip
    out_dir = tmp_path / "out"
    entries = extract_zip(str(gbk_zip), str(out_dir))
    names = sorted(e["rel_path"] for e in entries["files"])
    assert "外壳说明.txt" in names
    assert "drawings/图纸_A.step" in names
    assert any("nested.zip" in n for n in names)
    # 嵌套 zip 已递归展开一层
    assert any("内部/readme.txt" in n for n in names)
    # 文件真实落盘
    assert (out_dir / "外壳说明.txt").read_bytes() == b"top text"
    assert entries["ok"] is True


def test_extract_zip_rejects_slip(slip_zip: Path, tmp_path: Path):
    from services.file_intake import extract_zip
    out_dir = tmp_path / "out2"
    entries = extract_zip(str(slip_zip), str(out_dir))
    escaped = [e for e in entries["rejected"] if e["reason"] == "zip_slip"]
    assert {e["name"] for e in escaped} == {"../escape.txt", "/abs_escape.txt"}
    # 穿越文件绝不落盘
    assert not (tmp_path / "escape.txt").exists()
    assert not (out_dir.parent / "abs_escape.txt").exists()
    ok_names = sorted(e["rel_path"] for e in entries["files"])
    assert "good.txt" in ok_names
    assert any("also_good" in n for n in ok_names)


def test_extract_zip_depth_limit(gbk_zip: Path, tmp_path: Path):
    from services.file_intake import extract_zip
    r = extract_zip(str(gbk_zip), str(tmp_path / "d0"), max_depth=1)
    # 深度 1: 只解外层, nested.zip 作为普通文件保留, 不递归
    assert not any("内部" in e["rel_path"] for e in r["files"])


# ---------- classify / parse_any 路由 ----------
def test_classify_zip():
    from services.file_intake import classify
    assert classify("a.zip") == "zip"


def test_parse_any_zip_routes_to_extractor(gbk_zip: Path, tmp_path: Path):
    from services.file_intake import parse_any
    r = parse_any(str(gbk_zip), extract_dir=str(tmp_path / "pa"))
    assert r["ok"] is True
    assert r["kind"] == "zip"
    assert r["n_files"] >= 3
