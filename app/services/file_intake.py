"""file_intake.py — 全模态数据解析器 (上传端口后端).

支持"所有数据"的落地解析, 每种模态产出 canonical evidence + 结构化字段:
  email (.eml/.msg/.txt)  → stdlib email 解析 subject/from/body
  step  (.step/.stp)      → 真实 OCP B-rep 几何 (bbox/体积/重量) + C1 特征
  audio (.wav/.mp3/...)   → funasr ASR 转写 (离线显式 MOCK)
  pdf   (.pdf)            → pypdf 文本 (缺库则显式标注 skipped)
  excel (.xlsx/.xls/.csv) → openpyxl/csv 行数据 (缺库则显式标注 skipped)
  image (.png/.jpg)       → 交给 VLM (funasr :1234) 感知, 只出感知结果不定价格
  zip   (.zip)            → 安全解包 (C1): GBK/cp437 文件名解码 + 嵌套递归 + zip-slip 拒绝

原则: 缺依赖/解析失败**显式标注** (skipped/error/mock), 绝不静默伪造。
"""
from __future__ import annotations

import csv
import email
import json
import re
import zipfile
from email import policy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .security import safe_filename

AUDIO_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".wma", ".mp4", ".mov"}
STEP_EXT = {".step", ".stp"}
PDF_EXT = {".pdf"}
EXCEL_EXT = {".xlsx", ".xlsm", ".xls", ".csv", ".tsv"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
EMAIL_EXT = {".eml", ".msg", ".txt"}
ZIP_EXT = {".zip"}
MAX_EXTRACTED_BYTES = 200 * 1024 * 1024   # 解压总量上限 (zip bomb 缓解)
MAX_ZIP_DEPTH = 3


def classify(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in ZIP_EXT:
        return "zip"
    if ext in STEP_EXT:
        return "step"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in PDF_EXT:
        return "pdf"
    if ext in EXCEL_EXT:
        return "excel"
    if ext in IMAGE_EXT:
        return "image"
    if ext in EMAIL_EXT:
        return "email"
    return "unknown"


# ---------------- email ----------------
def parse_email_file(path: str) -> Dict[str, Any]:
    raw = Path(path).read_bytes()
    try:
        msg = email.message_from_bytes(raw, policy=policy.default)
        subject = str(msg.get("subject", ""))
        sender = str(msg.get("from", ""))
        to = str(msg.get("to", ""))
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_content()
                    break
            if not body:
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        body = part.get_content()
                        break
        else:
            body = msg.get_content() if msg.get_content_maintype() == "text" else ""
        attachments = [p.get_filename() for p in msg.walk()
                       if p.get_filename()] if msg.is_multipart() else []
        return {"ok": True, "subject": subject, "from": sender, "to": to,
                "body": str(body).strip(), "attachments": attachments,
                "_source": "stdlib:email"}
    except UnicodeDecodeError:
        # 纯文本邮件
        return {"ok": True, "subject": "", "from": "", "to": "",
                "body": raw.decode("utf-8", "ignore").strip(), "attachments": [],
                "_source": "plaintext"}
    except Exception as e:  # noqa
        return {"ok": False, "error": repr(e), "body": raw.decode("utf-8", "ignore"),
                "_source": "error"}


# ---------------- step (real OCP geometry) ----------------
def parse_step(path: str, timo, material: str = "6061", with_features: bool = False) -> Dict[str, Any]:
    geo = timo.step_geometry(path, material=material)
    out: Dict[str, Any] = {"ok": not geo.get("error"), "geometry": geo, "_source": geo.get("_source")}
    if with_features:
        out["features"] = timo.step_features(path)
    return out


# ---------------- audio (funasr ASR) ----------------
def parse_audio(path: str, funasr, mock_text: Optional[str] = None) -> Dict[str, Any]:
    if funasr is None:
        return {"ok": False, "text": mock_text or "", "_mock": True, "_source": "MOCK:no-adapter"}
    r = funasr.transcribe(path, mock_text=mock_text)
    return {"ok": True, "text": r.get("text", ""), "_mock": r.get("_mock", False),
            "_source": r.get("_source")}


# ---------------- pdf ----------------
def parse_pdf(path: str) -> Dict[str, Any]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except Exception:
            return {"ok": False, "skipped": True, "reason": "pypdf not installed",
                    "text": "", "_source": "skipped"}
    try:
        r = PdfReader(path)
        text = "\n".join((p.extract_text() or "") for p in r.pages[:20])
        return {"ok": True, "text": text.strip(), "pages": len(r.pages), "_source": "pypdf"}
    except Exception as e:  # noqa
        return {"ok": False, "error": repr(e), "text": "", "_source": "error"}


# ---------------- excel / csv ----------------
def parse_excel(path: str, max_rows: int = 200) -> Dict[str, Any]:
    p = Path(path)
    if p.suffix.lower() in (".csv", ".tsv"):
        delim = "\t" if p.suffix.lower() == ".tsv" else ","
        try:
            with open(p, "r", encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.reader(fh, delimiter=delim))[:max_rows]
            return {"ok": True, "rows": rows, "n_rows": len(rows), "_source": "csv"}
        except Exception as e:  # noqa
            return {"ok": False, "error": repr(e), "_source": "error"}
    try:
        import openpyxl  # type: ignore
    except Exception:
        return {"ok": False, "skipped": True, "reason": "openpyxl not installed",
                "rows": [], "_source": "skipped"}
    try:
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        ws = wb.active
        rows: List[List[Any]] = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= max_rows:
                break
            rows.append([c for c in row])
        wb.close()
        return {"ok": True, "rows": rows, "n_rows": len(rows), "_source": "openpyxl"}
    except Exception as e:  # noqa
        return {"ok": False, "error": repr(e), "_source": "error"}


# ---------------- image (VLM 感知, 只出感知结果) ----------------
def parse_image(path: str, funasr) -> Dict[str, Any]:
    """图纸/图片 → VLM 感知 (qwen3.8-27b @ :1234). 只出感知事实, 不决定价格。
    适配器缺失或 VLM 离线 → 显式 MOCK, 不冒充生产感知。"""
    if funasr is None:
        return {"ok": False, "skipped": True, "perception": None, "_mock": True,
                "reason": "no funasr adapter", "_source": "MOCK:no-adapter"}
    r = funasr.perceive_image(path)
    return {"ok": bool(r.get("ok")), "perception": r.get("perception"),
            "_mock": r.get("_mock", True), "_source": r.get("_source"),
            "skipped": bool(r.get("_mock", True))}


# ---------------- zip (C1 安全解包) ----------------
def decode_zip_name(raw: bytes, utf8_flag: bool) -> str:
    """zip 条目名 → str. UTF-8 flag 走 utf-8; 否则 GBK 优先, 非法序列 cp437 兜底。"""
    if utf8_flag:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            pass
    try:
        return raw.decode("gbk")
    except UnicodeDecodeError:
        return raw.decode("cp437")


def _sanitize_rel(name: str) -> Tuple[Optional[List[str]], Optional[str]]:
    """路径清洗: 拒绝绝对/盘符/越出根的 '..'; 各段过 safe_filename。"""
    n = name.replace("\\", "/")
    if n.startswith("/") or re.match(r"^[A-Za-z]:", n):
        return None, "zip_slip"
    parts: List[str] = []
    for seg in n.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not parts:
                return None, "zip_slip"
            parts.pop()
            continue
        cleaned = safe_filename(seg)
        if cleaned:
            parts.append(cleaned)
    if not parts:
        return None, "bad_name"
    return parts, None


def extract_zip(zip_path: str, dest_dir: str, max_depth: int = MAX_ZIP_DEPTH) -> Dict[str, Any]:
    """安全解包 (防 zip slip / 绝对路径 / zip bomb), GBK 文件名解码, 嵌套 zip 递归。

    返回 {ok, files:[{rel_path,size,kind}], rejected:[{name,reason}], total_bytes}。
    被拒绝的条目**绝不落盘**, 且显式列出让上层可见。
    """
    files: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    total = 0
    dest_root = Path(dest_dir).resolve()

    def _walk(zpath: str, prefix: str, depth: int) -> None:
        nonlocal total
        with zipfile.ZipFile(zpath) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                utf8_flag = bool(info.flag_bits & 0x800)
                try:
                    raw = info.filename.encode("cp437" if not utf8_flag else "utf-8")
                except UnicodeEncodeError:
                    raw = info.filename.encode("utf-8")
                    utf8_flag = True
                name = decode_zip_name(raw, utf8_flag)
                parts, err = _sanitize_rel(name)
                if err:
                    rejected.append({"name": name, "reason": err})
                    continue
                rel = "/".join(([prefix] if prefix else []) + parts)
                target = (dest_root / Path(prefix) / Path(*parts) if prefix
                          else dest_root / Path(*parts))
                try:
                    if target.resolve().relative_to(dest_root):
                        pass
                except ValueError:
                    rejected.append({"name": name, "reason": "zip_slip"})
                    continue
                is_nested = name.lower().endswith(".zip") and depth < max_depth
                if is_nested:
                    # 嵌套 zip 解到 "<zip路径>_extracted" 子目录, 避免与 zip 文件同名冲突
                    inner_prefix = "/".join(
                        ([prefix] if prefix else [])
                        + parts[:-1] + [parts[-1] + "_extracted"])
                else:
                    inner_prefix = ""
                target.parent.mkdir(parents=True, exist_ok=True)
                data = zf.read(info)
                total += len(data)
                if total > MAX_EXTRACTED_BYTES:
                    rejected.append({"name": name, "reason": "size_limit"})
                    return
                target.write_bytes(data)
                files.append({"rel_path": rel, "size": len(data), "kind": classify(name)})
                if is_nested:
                    _walk(str(target), inner_prefix, depth + 1)

    try:
        _walk(zip_path, "", 1)
    except zipfile.BadZipFile as e:
        return {"ok": False, "error": repr(e), "files": files, "rejected": rejected,
                "_source": "error"}
    return {"ok": True, "files": files, "rejected": rejected, "total_bytes": total,
            "_source": "stdlib:zipfile"}


# ---------------- RAG 入库文本抽取 ----------------
def doc_text(path: str) -> Dict[str, Any]:
    """任意已落盘文件 → {ok, text, kind, reason?}: 供 RAG ingestion 用。

    与 parse_any 不同: 目标是拿到**可嵌入文本**, 拿不到就显式 skipped, 不静默。
    """
    kind = classify(path)
    if kind == "email":
        r = parse_email_file(path)
        text = "\n".join(x for x in (r.get("subject"), r.get("body")) if x)
        return {"ok": bool(text.strip()), "kind": kind, "text": text,
                "reason": None if text.strip() else "empty"}
    if kind == "excel":
        r = parse_excel(path)
        if not r.get("ok"):
            return {"ok": False, "kind": kind, "text": "", "reason": str(r.get("reason") or r.get("error"))}
        text = "\n".join(",".join(str(c) for c in row if c is not None) for row in r["rows"])
        return {"ok": True, "kind": kind, "text": text}
    if kind == "pdf":
        r = parse_pdf(path)
        if not r.get("ok"):
            return {"ok": False, "kind": kind, "text": "", "reason": str(r.get("reason") or r.get("error"))}
        return {"ok": True, "kind": kind, "text": r["text"]}
    if kind == "audio":
        return {"ok": False, "kind": kind, "text": "",
                "reason": "audio 需 ASR 转写后单独入库 (funasr 在线时走转写链路)"}
    if kind == "step":
        try:
            head = Path(path).read_text(encoding="utf-8", errors="ignore")[:4000]
            return {"ok": bool(head.strip()), "kind": kind, "text": head}
        except OSError as e:
            return {"ok": False, "kind": kind, "text": "", "reason": repr(e)}
    if kind in ("image", "zip", "unknown"):
        return {"ok": False, "kind": kind, "text": "", "reason": f"no text for kind={kind}"}
    # 未知扩展名尝试纯文本
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore").strip()
    except OSError as e:
        return {"ok": False, "kind": kind, "text": "", "reason": repr(e)}
    return {"ok": bool(text), "kind": kind, "text": text,
            "reason": None if text else "empty"}


# ---------------- 统一入口 ----------------
def parse_any(path: str, timo=None, funasr=None, material: str = "6061",
              mock_text: Optional[str] = None,
              extract_dir: Optional[str] = None) -> Dict[str, Any]:
    kind = classify(path)
    if kind == "zip":
        dest = extract_dir or str(Path(path).with_suffix("")) + "_extracted"
        r = extract_zip(path, dest)
        r["n_files"] = len(r["files"])
    elif kind == "email":
        r = parse_email_file(path)
    elif kind == "step":
        if timo is None:
            return {"ok": False, "skipped": True, "reason": "no timo adapter", "kind": kind}
        r = parse_step(path, timo, material=material, with_features=True)
    elif kind == "audio":
        r = parse_audio(path, funasr, mock_text=mock_text)
    elif kind == "pdf":
        r = parse_pdf(path)
    elif kind == "excel":
        r = parse_excel(path)
    elif kind == "image":
        r = parse_image(path, funasr)
    else:
        r = {"ok": False, "skipped": True, "reason": f"unknown type {Path(path).suffix}"}
    r["kind"] = kind
    r["path"] = str(path)
    return r


if __name__ == "__main__":
    import sys
    print(json.dumps({"classify .STEP": classify("a.STEP"), "classify .eml": classify("b.eml"),
                      "classify .wav": classify("c.wav"), "classify .xlsx": classify("d.xlsx")},
                     ensure_ascii=False))
    if len(sys.argv) > 1:
        print(json.dumps(parse_email_file(sys.argv[1]), ensure_ascii=False)[:400])
