"""test_desensitize.py — v2.3.0 供应商流水线·安全门禁。

数据脱敏硬门禁：脱敏后 ZIP 内必须**零客户字符串泄漏**。
测试断言：所有传入的客户 PII（姓名/邮箱/电话/地址/项目号/标题栏/图纸元数据/文件名）
          在 ZIP 内全部不可见；客户指纹 SHA-256 稳定；文件结构保留。
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile

import pytest

from supplier_module.desensitize import (
    DesensitizeRequest,
    DesensitizedPackage,
    desensitize,
    fingerprint_customer,
)


# ---- 测试夹具：客户/图纸样本 ----
CUSTOMER_FULL = {
    "name": "Acme Industrial Co., Ltd.",
    "contact_person": "John Smith",
    "email": "john.smith@acme-industrial.com",
    "phone": "13800138000",
    "address": "123 Customer Street, Suite 500, New York, NY 10001, USA",
    "project_code": "ACME-2026-001",
    "company_registration": "US-REG-12345678",
}

# 模拟一个带客户署名的 STEP 文件头
STEP_WITH_HEADER = b"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('Customer: Acme Industrial Co., Ltd. Project: ACME-2026-001'));
FILE_NAME('bracket_ACME-2026-001.step','2026-09-18T10:00:00',('john.smith@acme-industrial.com'),('John Smith'),'acme-cad-v8','Acme Industrial');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));
ENDSEC;
DATA;
#1 = APPLICATION_CONTEXT('mechanical design');
ENDSEC;
END-ISO-10303-21;
"""

# 模拟一个带客户元数据的 PDF 头（最小 PDF，仅 /Info）
PDF_WITH_INFO = b"""%PDF-1.4
%\xe2\xe3\xcf\xd3
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>
endobj
4 0 obj
<< /Title (Acme Industrial Bracket Drawing ACME-2026-001)
/Author (John Smith <john.smith@acme-industrial.com>)
/Producer (acme-cad-v8)
/Creator (Acme Industrial)
/Subject (Project ACME-2026-001 for John Smith) >>
endobj
xref
0 5
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000210 00000 n
trailer
<< /Size 5 /Root 1 0 R /Info 4 0 R >>
startxref
400
%%EOF
"""

# 标题栏文字（模拟一份图纸的"标题栏"区域 ASCII 描述）
TITLE_BLOCK_TEXT = (
    "DRAWING TITLE: BRACKET-A | "
    "CUSTOMER: Acme Industrial Co., Ltd. | "
    "PROJECT: ACME-2026-001 | "
    "DRAWN BY: John Smith | "
    "EMAIL: john.smith@acme-industrial.com | "
    "TEL: 13800138000"
).encode("utf-8")


def _make_req(files=None, customer=None, context_id="ctx-test-001"):
    return DesensitizeRequest(
        context_id=context_id,
        customer=customer or dict(CUSTOMER_FULL),
        files=files or [],
    )


def _make_step_req():
    return _make_req(
        files=[
            ("bracket_ACME-2026-001.step", STEP_WITH_HEADER, "step"),
        ]
    )


def _make_pdf_req():
    return _make_req(
        files=[
            ("drawing_ACME-2026-001.pdf", PDF_WITH_INFO, "pdf"),
        ]
    )


def _make_full_req():
    return _make_req(
        files=[
            ("bracket_ACME-2026-001.step", STEP_WITH_HEADER, "step"),
            ("drawing_ACME-2026-001.pdf", PDF_WITH_INFO, "pdf"),
            ("titleblock_ACME-2026-001.txt", TITLE_BLOCK_TEXT, "text"),
        ]
    )


# ---- 1. 客户指纹稳定性 ----

def test_fingerprint_is_stable_for_same_customer():
    fp1 = fingerprint_customer(CUSTOMER_FULL)
    fp2 = fingerprint_customer(CUSTOMER_FULL)
    assert fp1 == fp2
    assert len(fp1) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", fp1)


def test_fingerprint_changes_when_customer_differs():
    a = dict(CUSTOMER_FULL)
    b = dict(CUSTOMER_FULL)
    b["email"] = "other@acme.com"
    assert fingerprint_customer(a) != fingerprint_customer(b)


def test_fingerprint_is_salted_and_not_reversible_in_output():
    """指纹不能由客户字段直接推回；验证它不含明文片段。"""
    fp = fingerprint_customer(CUSTOMER_FULL)
    # 指纹不应包含客户字段的明文片段
    for s in ("Acme", "ACME-2026", "13800138000", "john.smith"):
        assert s.lower() not in fp.lower()


# ---- 2. ZIP 结构 ----

def test_zip_contains_manifest():
    pkg = desensitize(_make_step_req())
    with zipfile.ZipFile(io.BytesIO(pkg.zip_bytes)) as z:
        names = z.namelist()
    assert any(n.endswith("manifest.json") for n in names)


def test_zip_preserves_file_count():
    pkg = desensitize(_make_full_req())
    with zipfile.ZipFile(io.BytesIO(pkg.zip_bytes)) as z:
        # 3 原始文件 + manifest
        non_meta = [n for n in z.namelist() if not n.endswith("manifest.json")]
        assert len(non_meta) == 3


def test_manifest_contains_fingerprint_and_context_id():
    pkg = desensitize(_make_step_req())
    with zipfile.ZipFile(io.BytesIO(pkg.zip_bytes)) as z:
        import json
        manifest = json.loads(z.read("manifest.json"))
    assert manifest["context_id"] == "ctx-test-001"
    assert manifest["customer_fingerprint"] == pkg.customer_fingerprint
    assert "files" in manifest and len(manifest["files"]) == 1


# ---- 3. 零客户字符串泄漏（硬门禁） ----

def test_step_header_pii_is_stripped():
    pkg = desensitize(_make_step_req())
    with zipfile.ZipFile(io.BytesIO(pkg.zip_bytes)) as z:
        all_bytes = b"".join(z.read(n) for n in z.namelist() if not n.endswith("manifest.json"))
        txt = all_bytes.decode("utf-8", errors="ignore")
    # 客户身份相关字符串
    assert "Acme Industrial" not in txt
    assert "ACME-2026-001" not in txt
    assert "john.smith" not in txt
    assert "13800138000" not in txt
    # 但 STEP 结构必须保留（FILE_DESCRIPTION 等可换为通用描述）
    assert "ISO-10303-21" in txt


def test_pdf_info_pii_is_stripped():
    pkg = desensitize(_make_pdf_req())
    with zipfile.ZipFile(io.BytesIO(pkg.zip_bytes)) as z:
        all_bytes = b"".join(z.read(n) for n in z.namelist() if not n.endswith("manifest.json"))
        txt = all_bytes.decode("latin-1", errors="ignore")
    assert "Acme Industrial" not in txt
    assert "ACME-2026-001" not in txt
    assert "john.smith" not in txt
    # 元数据键保留但值已擦（PDF 结构必需）
    assert "/Author" in txt
    assert "/Title" in txt
    # 且值已空
    assert "/Author()" in txt or "/Author ()" in txt
    # PDF 头必须保留
    assert txt.startswith("%PDF-1")


def test_title_block_text_is_pii_stripped():
    pkg = desensitize(_make_full_req())
    with zipfile.ZipFile(io.BytesIO(pkg.zip_bytes)) as z:
        all_bytes = b"".join(z.read(n) for n in z.namelist() if not n.endswith("manifest.json"))
        txt = all_bytes.decode("utf-8", errors="ignore")
    for needle in ("Acme Industrial", "ACME-2026-001", "John Smith",
                   "john.smith@acme-industrial.com", "13800138000"):
        assert needle not in txt, f"{needle!r} still present in ZIP"


def test_filename_is_anonymized_no_customer_leak():
    pkg = desensitize(_make_full_req())
    with zipfile.ZipFile(io.BytesIO(pkg.zip_bytes)) as z:
        names = z.namelist()
    # 文件名不应包含客户项目号
    for n in names:
        assert "ACME-2026-001" not in n
        assert "Acme" not in n
    # 但应有文件
    assert len(names) >= 2


def test_zip_globally_contains_no_customer_pii():
    """终极断言：整个 ZIP（除 manifest 内受控字段外）不得出现任何客户 PII。"""
    pkg = desensitize(_make_full_req())
    with zipfile.ZipFile(io.BytesIO(pkg.zip_bytes)) as z:
        for n in z.namelist():
            data = z.read(n)
            if n.endswith("manifest.json"):
                # manifest 允许有 fingerprint，但不应有原始 PII
                import json
                m = json.loads(data)
                dumped = json.dumps(m)
            else:
                dumped = data.decode("utf-8", errors="ignore")
            for needle in ("Acme Industrial", "John Smith",
                           "john.smith@acme-industrial.com",
                           "13800138000", "ACME-2026-001",
                           "New York", "US-REG-12345678"):
                assert needle not in dumped, f"泄漏: {needle!r} in {n}"


# ---- 4. 失败策略 ----

def test_missing_critical_field_raises():
    bad = dict(CUSTOMER_FULL)
    del bad["email"]
    with pytest.raises(ValueError, match="email"):
        desensitize(_make_req(customer=bad))


def test_empty_files_is_allowed_but_manifest_present():
    pkg = desensitize(_make_req())  # 无文件
    with zipfile.ZipFile(io.BytesIO(pkg.zip_bytes)) as z:
        names = z.namelist()
    assert "manifest.json" in names
    assert len(names) == 1


# ---- 5. 与现有 security.redact 一致 ----

def test_redacted_fields_recorded_in_data_class():
    pkg = desensitize(_make_full_req())
    # 至少标记了几个字段
    assert isinstance(pkg.redacted_fields, list)
    assert len(pkg.redacted_fields) > 0


# ---- 6. customer_fingerprint 与 manifest 一致 ----

def test_fingerprint_matches_manifest():
    pkg = desensitize(_make_full_req())
    import json
    with zipfile.ZipFile(io.BytesIO(pkg.zip_bytes)) as z:
        manifest = json.loads(z.read("manifest.json"))
    assert manifest["customer_fingerprint"] == pkg.customer_fingerprint
    # 指纹本身是 64hex
    assert re.fullmatch(r"[0-9a-f]{64}", pkg.customer_fingerprint)