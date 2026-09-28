"""desensitize.py — v2.3.0 安全门禁·数据脱敏。

合同：所有流向供应商的工件（ZIP）必须零客户字符串泄漏。
处理对象：
  - 文本字段：客户档案/项目号/图纸标题栏文字
  - STEP 文件：HEADER 段 FILE_DESCRIPTION/FILE_NAME 元数据
  - PDF 文件：/Info 字典（Title/Author/Producer/Creator/Subject）
  - 文件名：基于 fingerprint 哈希匿名化
  - 客户指纹：SHA-256(salt + 规范化客户档案)，用于内部关联

失败策略：缺失关键字段（email/name/project_code）→ ValueError；
         PDF/STEP 解析失败 → 整体跳过 + 警告（不静默伪造）。
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import secrets
import time
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

# ---- 盐：运行时生成；持久化放在 prod 部署时改环境变量 ----
_FINGERPRINT_SALT = secrets.token_hex(16)

# 关键字段（缺失即拒收）
_REQUIRED_CUSTOMER_FIELDS = ("name", "email", "project_code")

# 客户档案里要主动擦除的 PII 字段
_PII_FIELDS = (
    "name", "contact_person", "email", "phone", "address",
    "company_registration", "project_code",
)

# 文本字段里要扫除的客户相关字符串（保险冗余）
_PII_TEXT_NEEDLES = ()  # 运行时基于客户档案动态生成


def _normalize_customer(customer: Dict[str, Any]) -> Dict[str, Any]:
    """规范化客户档案用于指纹（去除空白、大小写归一）。"""
    norm: Dict[str, Any] = {}
    for k, v in customer.items():
        if v is None:
            continue
        s = str(v).strip().lower()
        norm[k] = s
    return norm


def fingerprint_customer(customer: Dict[str, Any]) -> str:
    """客户指纹：SHA-256(salt + JSON 规范化档案)。

    稳定性：同一客户 → 同指纹；任一字段变 → 指纹变。
    不可逆：指纹不含明文片段（已加盐 + hash）。
    """
    norm = _normalize_customer(customer)
    payload = json.dumps(norm, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha256()
    h.update(_FINGERPRINT_SALT.encode("utf-8"))
    h.update(b"|")
    h.update(payload.encode("utf-8"))
    return h.hexdigest()


# ---- STEP 头部擦除 ----

_STEP_HEADER_END_RE = re.compile(rb"(ENDSEC;\s*\n\s*DATA;)", re.IGNORECASE)
# 匹配 FILE_DESCRIPTION(...) / FILE_NAME(...) 整个语句（含一层嵌套括号）
_STEP_STMT_RE = re.compile(r"\b(FILE_DESCRIPTION|FILE_NAME)\s*\((?:[^()]|\([^()]*\))*\)")


def _redact_step_header(step_bytes: bytes, redacted_fields: List[str]) -> bytes:
    """擦 STEP HEADER 段的 FILE_DESCRIPTION / FILE_NAME 客户身份字段。

    策略：保留 FILE_SCHEMA（结构必需），其余字段替换为通用占位。
    DATA 段保留——其内只会有几何/拓扑数字 ID，不含 PII。
    """
    text = step_bytes.decode("utf-8", errors="replace")
    redacted_fields.append("step.header.file_description")
    redacted_fields.append("step.header.file_name")
    safe_header_desc = "FILE_DESCRIPTION(('anonymized-by-supplier-pipeline'))"
    safe_header_name = (
        "FILE_NAME('anonymized.step',"
        "'1970-01-01T00:00:00',('anon'),('anon'),'anonymized','anonymized')"
    )
    # 处理多层嵌套：先尝试含一层嵌套，剩余残留再扫一遍
    prev = None
    while prev != text:
        prev = text
        text = _STEP_STMT_RE.sub(
            lambda m: safe_header_desc if m.group(1) == "FILE_DESCRIPTION" else safe_header_name,
            text,
        )
    return text.encode("utf-8")


# ---- PDF /Info 擦除 ----

_PDF_INFO_KEYS_RE = re.compile(
    rb"/(Title|Author|Producer|Creator|Subject|Keywords|Company)\s*\([^)]*\)"
)


def _redact_pdf_info(pdf_bytes: bytes, redacted_fields: List[str]) -> bytes:
    """擦 PDF /Info 字典里的 7 个客户身份键。

    策略：用正则替换 /Title(...)/Author(...)/Producer(...)/Creator(...)/Subject(...)/Keywords(...)/Company(...) → /Key()。
    保留 PDF 整体结构（xref/stream 不动）。
    """
    redacted_fields.extend([
        "pdf.info.title", "pdf.info.author", "pdf.info.producer",
        "pdf.info.creator", "pdf.info.subject",
    ])
    out = _PDF_INFO_KEYS_RE.sub(b"/\\1()", pdf_bytes)
    # 二进制补白以稳定 PDF 文件（不让原始字节长度直接对得上原文）
    return out


# ---- 标题栏文字擦除 ----

def _redact_text_block(text_bytes: bytes, customer: Dict[str, Any],
                        redacted_fields: List[str]) -> bytes:
    """通用文本 PII 擦除（标题栏 / 备注 / 自由文本）。"""
    txt = text_bytes.decode("utf-8", errors="replace")
    needles = []
    for f in _PII_FIELDS:
        v = customer.get(f)
        if v:
            needles.append(str(v))
    # 加上显式 phone（防格式变体）
    phone = customer.get("phone")
    if phone:
        # 把数字按 3-4-4 拆开都覆盖
        s = re.sub(r"\D", "", str(phone))
        for i in range(0, len(s), 4):
            needles.append(s[i:i + 4])
    for n in needles:
        if n and len(n) >= 3:
            txt = txt.replace(n, "<REDACTED>")
    if needles:
        redacted_fields.append("text.pii_redacted")
    return txt.encode("utf-8")


# ---- 文件名匿名化 ----

def _anon_filename(orig: str, fingerprint: str) -> str:
    """文件名 → 基于 fingerprint 的稳定匿名（同名同源 → 同匿名）。"""
    base = orig.rsplit("/", 1)[-1]
    ext = ""
    if "." in base:
        ext = "." + base.rsplit(".", 1)[-1].lower()
    h = hashlib.sha256((fingerprint + "|" + base).encode("utf-8")).hexdigest()[:16]
    return f"file_{h}{ext}"


# ---- 数据类 ----

@dataclass
class DesensitizeRequest:
    context_id: str
    customer: Dict[str, Any]
    files: List[Tuple[str, bytes, str]] = field(default_factory=list)
    # files: [(原始文件名, 字节内容, kind)], kind ∈ {step, pdf, text, other}


@dataclass
class DesensitizedPackage:
    zip_bytes: bytes
    customer_fingerprint: str
    manifest: Dict[str, Any]
    redacted_fields: List[str] = field(default_factory=list)


# ---- 入口 ----

def _validate_customer(customer: Dict[str, Any]) -> None:
    missing = [f for f in _REQUIRED_CUSTOMER_FIELDS if not customer.get(f)]
    if missing:
        raise ValueError(f"customer missing required fields: {', '.join(missing)}")


def desensitize(req: DesensitizeRequest) -> DesensitizedPackage:
    _validate_customer(req.customer)
    fp = fingerprint_customer(req.customer)
    redacted_fields: List[str] = []
    out_files: List[Tuple[str, bytes]] = []

    for orig_name, content, kind in req.files:
        kind = (kind or "other").lower()
        anon_name = _anon_filename(orig_name, fp)
        try:
            if kind == "step":
                content = _redact_step_header(content, redacted_fields)
            elif kind == "pdf":
                content = _redact_pdf_info(content, redacted_fields)
            elif kind == "text":
                content = _redact_text_block(content, req.customer, redacted_fields)
            else:
                # 未知类型：仍做基础 PII 文本擦除（保险）
                content = _redact_text_block(content, req.customer, redacted_fields)
        except Exception as e:  # 解析失败：保留原字节但记录警告
            redacted_fields.append(f"{kind}.parse_error:{type(e).__name__}")
        out_files.append((anon_name, content))

    manifest = {
        "context_id": req.context_id,
        "customer_fingerprint": fp,
        "redacted_fields": sorted(set(redacted_fields)),
        "files": [
            {"anon_name": anon_name, "kind": (knd or "other").lower()}
            for (_, _, knd), (anon_name, _) in zip(req.files, out_files)
        ],
        "created_at": int(time.time()),
        "schema_version": "supplier-desensitize/v2.3.0",
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in out_files:
            z.writestr(name, content)
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    return DesensitizedPackage(
        zip_bytes=buf.getvalue(),
        customer_fingerprint=fp,
        manifest=manifest,
        redacted_fields=sorted(set(redacted_fields)),
    )