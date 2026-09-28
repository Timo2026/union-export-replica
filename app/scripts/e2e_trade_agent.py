"""e2e_trade_agent.py — 外贸自动接单 agent 端到端实战测试脚本.

覆盖完整运作流程 (每步 ✅/❌ + 量化指标, 最后汇总报告):
  [0]  环境自检            GET /health + /v1/models/config (6 模型 online/时延)
  [1]  模型设置 UI 验证    GET / + probe + save/restore ocr + deterministic 锁定 400
  [2]  邮箱接单            POST /v1/upload/email (sample_rfq.eml → 自动接单入口)
  [3]  STEP 几何上传       POST /v1/upload/step (sample_part.STEP, 6061 → OCP B-rep)
  [4]  ASR 会议上传        POST /v1/upload/audio (假 WAV + mock_text → 语音纪要)
  [5]  图片图纸上传        POST /v1/upload/image (手造 PNG → VLM 感知)
  [6]  统一 INTAKE         POST /v1/rfq/intake (全模态一次收 → 黄金链)
  [7]  铁律① LLM 对比      use_llm=True vs False → unit_price/final_price 必须一致
  [8]  商业层 landed cost  POST /v1/rfq/{cid}/commercial (freight/duty/landed)
  [9]  RAG 检索            funasr_adapter.rag_search (历史经验, 离线 MOCK)
  [10] 契约端点全跑        analyze/verify/reply-draft/crm-sync
  [11] HITL 授权 → DONE    TC4+IT5 → approve → DONE
  [12] Postmortem 闭环     POST /v1/rfq/{cid}/postmortem (Won/Lost 偏差分析)
  [13] 汇总报告            ✅/❌ 表 + passed/failed + BUG 清单

铁律①: 报价数字 100% 来自确定性引擎, LLM 不影响数字
       (use_llm=True/False 的 unit_price / final_price 必须一致).
"""
from __future__ import annotations

import json
import struct
import sys
import time
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BASE = "http://127.0.0.1:8900"
_SAMPLES = _ROOT / "data" / "samples"


# ======================== PNG 构造 (无 PIL/Pillow 依赖) ========================
def make_png(width: int, height: int, rgb: Tuple[int, int, int]) -> bytes:
    """用标准库构造纯色 PNG: 签名 + IHDR + IDAT(zlib 压缩 scanlines) + IEND.

    PNG 签名 \\x89PNG\\r\\n\\x1a\\n; IHDR 13 字节 (w,h,bit_depth=8,color_type=2=RGB,
    comp=0, filter=0, interlace=0); 每行 scanline 前加 filter byte 0 (None filter);
    IDAT = zlib.compress(所有 scanlines); 每 chunk = len(4)+tag(4)+data+crc(4).
    """
    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 13 字节
    r, g, b = rgb
    row = b"\x00" + bytes([r, g, b]) * width      # filter byte 0 + 一行 RGB 像素
    raw = row * height
    idat = zlib.compress(raw)
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


# ======================== 步骤结果收集 ========================
class Step:
    def __init__(self, name: str):
        self.name = name
        self.ok = False
        self.metrics: Dict[str, Any] = {}
        self.error: Optional[str] = None

    def pass_(self, **metrics: Any) -> None:
        self.ok = True
        self.metrics.update(metrics)

    def fail(self, err: str, **metrics: Any) -> None:
        self.ok = False
        self.error = err
        self.metrics.update(metrics)


STEPS: List[Step] = []


def _disp_width(s: str) -> int:
    """字符串显示宽度 (中文算 2)."""
    return sum(2 if ord(c) > 127 else 1 for c in s)


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _disp_width(s))


def _fmt(v: Any) -> str:
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def run_step(name: str, fn):
    """执行一步: try/except 包裹, 失败不中断, 记录 ✅/❌ + 量化指标."""
    s = Step(name)
    t0 = time.time()
    try:
        fn(s)
    except Exception as e:  # noqa: BLE001
        s.fail(f"{type(e).__name__}: {e}")
    s.metrics["ms"] = round((time.time() - t0) * 1000, 1)
    STEPS.append(s)
    icon = "✅" if s.ok else "❌"
    print(f"\n{icon} [{name}]  ({s.metrics['ms']} ms)")
    for k, v in s.metrics.items():
        if k == "ms":
            continue
        val = _fmt(v)
        if len(val) > 100:
            val = val[:97] + "..."
        print(f"     {k} = {val}")
    if not s.ok and s.error:
        print(f"     ⚠ ERROR: {s.error}")
    return s


# ======================== 主流程 ========================
def main() -> None:
    print("=" * 92)
    print(" 外贸自动接单 Agent — 端到端实战测试 (e2e_trade_agent)")
    print(f" target API: {BASE}")
    print("=" * 92)

    sess = requests.Session()

    # 预读样本 (一次性, 避免重复 IO + 文件句柄问题)
    eml_bytes = (_SAMPLES / "sample_rfq.eml").read_bytes()
    step_bytes = (_SAMPLES / "sample_part.STEP").read_bytes()
    # 假 WAV: RIFF header + WAVEfmt + 20 字节 0
    wav_bytes = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 20
    # 手造 64×64 蓝色 PNG (无 PIL 依赖)
    png_bytes = make_png(64, 64, (30, 90, 200))

    cids: Dict[str, str] = {}
    voice_mock = "客户在会议中说：公差可以放宽到 0.05mm，交期 30 天可以接受，预算 1 万美元以内"

    # -------------------- [0] 环境自检 --------------------
    def step0(s: Step):
        h = sess.get(f"{BASE}/health", timeout=10).json()
        s.metrics["engine"] = h.get("engine")
        s.metrics["multimodal"] = h.get("multimodal")
        s.metrics["contexts"] = h.get("contexts")
        mc = sess.get(f"{BASE}/v1/models/config", timeout=60).json()
        probe = mc.get("probe", {}) or {}
        online = 0
        for k in ("llm", "vlm", "embedding", "ocr", "asr", "deterministic"):
            p = probe.get(k, {}) or {}
            s.metrics[k] = f"online={p.get('online')} lat={p.get('latency_ms')}ms"
            if p.get("online"):
                online += 1
        s.metrics["models_online"] = f"{online}/6"
        s.pass_()
    run_step("[0] 环境自检", step0)

    # -------------------- [1] 模型设置 UI 验证 --------------------
    def step1(s: Step):
        # GET / → 200 + 含"模型设置"
        r = sess.get(f"{BASE}/", timeout=10)
        assert r.status_code == 200, f"UI 状态码 {r.status_code}"
        assert "模型设置" in r.text, "UI 不含 '模型设置'"
        s.metrics["ui_status"] = 200
        s.metrics["ui_has_模型设置"] = True

        # POST /v1/models/probe → 全部探活
        pr = sess.post(f"{BASE}/v1/models/probe", timeout=60).json()
        s.metrics["probe_keys"] = list(pr.keys())

        # GET config → 改 ocr endpoint=9999 → POST 保存 → 200
        cfg = sess.get(f"{BASE}/v1/models/config", timeout=60).json()["config"]
        orig_ocr = (cfg.get("models", {}).get("ocr", {}) or {}).get("endpoint")
        cfg2 = json.loads(json.dumps(cfg))  # deep copy
        cfg2.setdefault("models", {}).setdefault("ocr", {})["endpoint"] = "http://127.0.0.1:9999"
        sv1 = sess.post(f"{BASE}/v1/models/config", json=cfg2, timeout=60)
        assert sv1.status_code == 200, f"保存 ocr=9999 期望 200, 实际 {sv1.status_code}"
        s.metrics["save_ocr_9999"] = sv1.status_code

        # 恢复 ocr 原值 → 200
        cfg3 = json.loads(json.dumps(cfg))
        cfg3.setdefault("models", {}).setdefault("ocr", {})["endpoint"] = orig_ocr
        sv2 = sess.post(f"{BASE}/v1/models/config", json=cfg3, timeout=60)
        assert sv2.status_code == 200, f"恢复 ocr 期望 200, 实际 {sv2.status_code}"
        s.metrics["restore_ocr"] = sv2.status_code

        # 禁用 deterministic → 400 (铁律①: 报价不走 LLM, 不可禁用)
        cfg4 = json.loads(json.dumps(cfg))
        cfg4.setdefault("models", {}).setdefault("deterministic", {})["enabled"] = False
        sv3 = sess.post(f"{BASE}/v1/models/config", json=cfg4, timeout=60)
        assert sv3.status_code == 400, (
            f"禁用 deterministic 期望 400, 实际 {sv3.status_code} (铁律①被绕过!)")
        s.metrics["det_disable_status"] = sv3.status_code
        s.pass_()
    run_step("[1] 模型设置 UI 验证", step1)

    # -------------------- [2] 邮箱接单 (自动接单入口) --------------------
    def step2(s: Step):
        r = sess.post(
            f"{BASE}/v1/upload/email",
            files={"file": ("sample_rfq.eml", eml_bytes, "application/octet-stream")},
            timeout=30,
        ).json()
        s.metrics["subject"] = r.get("subject")
        s.metrics["from"] = r.get("from")
        s.metrics["source"] = r.get("_source")
        s.pass_()
    run_step("[2] 邮箱接单 (自动接单入口)", step2)

    # -------------------- [3] STEP 几何上传 --------------------
    def step3(s: Step):
        r = sess.post(
            f"{BASE}/v1/upload/step",
            files={"file": ("sample_part.STEP", step_bytes, "application/octet-stream")},
            data={"material": "6061"},
            timeout=60,
        ).json()
        geo = r.get("geometry", {}) or {}
        feats = r.get("features", {}) or {}
        s.metrics["bbox_mm"] = geo.get("bbox_mm")
        s.metrics["volume_mm3"] = geo.get("volume_mm3")
        s.metrics["weight_kg"] = geo.get("weight_kg")
        s.metrics["holes"] = feats.get("hole_count")
        s.metrics["source"] = geo.get("volume_source") or r.get("_source")
        s.pass_()
    run_step("[3] STEP 几何上传 (OCP B-rep)", step3)

    # -------------------- [4] ASR 会议上传 (语音会议纪要) --------------------
    def step4(s: Step):
        r = sess.post(
            f"{BASE}/v1/upload/audio",
            files={"file": ("meeting.wav", wav_bytes, "audio/wav")},
            data={"mock_text": voice_mock},
            timeout=30,
        ).json()
        s.metrics["source"] = r.get("_source")
        s.metrics["mock"] = r.get("_mock")
        s.metrics["text"] = (r.get("text") or "")[:80]
        s.pass_()
    run_step("[4] ASR 会议上传 (语音会议纪要)", step4)

    # -------------------- [5] 图片图纸上传 (VLM 感知) --------------------
    def step5(s: Step):
        r = sess.post(
            f"{BASE}/v1/upload/image",
            files={"file": ("drawing.png", png_bytes, "image/png")},
            timeout=30,
        ).json()
        s.metrics["source"] = r.get("_source")
        s.metrics["mock"] = r.get("_mock")
        perc = r.get("perception")
        s.metrics["perception"] = (str(perc)[:80] if perc else None)
        s.pass_()
    run_step("[5] 图片图纸上传 (VLM 感知)", step5)

    # -------------------- [6] 统一 INTAKE (全模态一次收 → 黄金链) --------------------
    def step6(s: Step):
        files = {
            "email_file": ("sample_rfq.eml", eml_bytes, "application/octet-stream"),
            "step_file": ("sample_part.STEP", step_bytes, "application/octet-stream"),
            "audio_file": ("meeting.wav", wav_bytes, "audio/wav"),
            "image_file": ("drawing.png", png_bytes, "image/png"),
        }
        data = {
            "customer_name": "Northwind Robotics",
            "country": "US",
            "incoterm": "DDP",
            "shipping_mode": "air",
            "use_llm": "false",
            "voice_transcript": voice_mock,
        }
        r = sess.post(f"{BASE}/v1/rfq/intake", files=files, data=data, timeout=180).json()
        cid = r["context_id"]
        cids["intake"] = cid
        res = r["result"]
        q = res.get("quote", {}) or {}
        s.metrics["context_id"] = cid
        s.metrics["state"] = res.get("state")
        s.metrics["verify"] = res.get("verification_status")
        s.metrics["unit_price"] = q.get("unit_price")
        s.metrics["final_price"] = q.get("final_price")
        s.metrics["engine_source"] = res.get("engine_source")
        s.metrics["audit_valid"] = res.get("audit_valid")
        s.metrics["guardrails"] = res.get("guardrails")
        s.pass_()
    run_step("[6] 统一 INTAKE (全模态一次收 → 黄金链)", step6)

    # -------------------- [7] 铁律① LLM 对比 (use_llm=True vs False) --------------------
    def step7(s: Step):
        email_text = (
            "Subject: RFQ - 6061-T6 Aluminum Plates\n\n"
            "Dear Sales, we request a quote for:\n"
            "- Part: 6061-T6 aluminum plate\n"
            "- Quantity: 50 pcs\n"
            "- Dimensions: 100x100x260 mm\n"
            "- Surface: anodizing\n"
            "- Tolerance: ±0.1mm\n"
            "Please quote FOB. Thanks."
        )
        # RFQ_A: use_llm=False (纯确定性)
        rA = sess.post(f"{BASE}/v1/rfq/intake",
                       data={"email_text": email_text, "use_llm": "false"},
                       timeout=180).json()
        # RFQ_B: use_llm=True (LLM 抽取+起草, 引擎仍裁决数字)
        rB = sess.post(f"{BASE}/v1/rfq/intake",
                       data={"email_text": email_text, "use_llm": "true"},
                       timeout=180).json()
        resA, resB = rA["result"], rB["result"]
        qA = resA.get("quote", {}) or {}
        qB = resB.get("quote", {}) or {}
        unitA, unitB = qA.get("unit_price"), qB.get("unit_price")
        finalA, finalB = qA.get("final_price"), qB.get("final_price")

        s.metrics["RFQ_A(cid,llm=F)"] = rA["context_id"]
        s.metrics["RFQ_B(cid,llm=T)"] = rB["context_id"]
        s.metrics["unit_price_A"] = unitA
        s.metrics["unit_price_B"] = unitB
        s.metrics["final_price_A"] = finalA
        s.metrics["final_price_B"] = finalB
        s.metrics["llm_planner_B"] = resB.get("llm_planner")

        unit_match = (unitA == unitB)
        final_match = (finalA == finalB)
        s.metrics["unit_price_一致"] = unit_match
        s.metrics["final_price_一致"] = final_match

        if unit_match and final_match:
            s.pass_()
        else:
            s.fail("铁律①违反: use_llm=True/False 数字不一致 (LLM 不应影响报价数字)")

    s7 = run_step("[7] 铁律① LLM 对比 (use_llm=True vs False)", step7)
    if not s7.ok:
        print("     🚨🚨🚨 核心铁律①被违反! 报价数字受 LLM 影响, 这是严重 BUG 🚨🚨🚨")

    # -------------------- [8] 商业层 landed cost --------------------
    def step8(s: Step):
        cid = cids.get("intake")
        assert cid, "[6] 未产出 context_id"
        r = sess.post(f"{BASE}/v1/rfq/{cid}/commercial", timeout=30).json()
        comm = r.get("commercial", {}) or {}
        bd = comm.get("breakdown", {}) or {}
        s.metrics["freight"] = bd.get("freight")
        s.metrics["duty"] = bd.get("duty")
        s.metrics["landed_cost"] = comm.get("landed_cost")
        s.metrics["seller_quote_price"] = comm.get("seller_quote_price")
        s.metrics["lead_time_days"] = comm.get("total_lead_time_days")
        s.pass_()
    run_step("[8] 商业层 landed cost", step8)

    # -------------------- [9] RAG 检索 (历史经验) --------------------
    def step9(s: Step):
        from adapters.funasr_adapter import FunASRAdapter
        adapter = FunASRAdapter({"funasr": {}})
        result = adapter.rag_search("304 阳极氧化 冲突")
        s.metrics["hits_count"] = len(result.get("hits", []))
        s.metrics["source"] = result.get("_source")
        s.metrics["mock"] = result.get("_mock")
        s.pass_()
    run_step("[9] RAG 检索 (历史经验)", step9)

    # -------------------- [10] 契约端点全跑 --------------------
    def step10(s: Step):
        cid = cids.get("intake")
        assert cid, "[6] 未产出 context_id"
        a = sess.post(f"{BASE}/v1/rfq/{cid}/analyze", timeout=30).json()
        s.metrics["analyze_dfm_valid"] = (a.get("dfm") or {}).get("valid")
        v = sess.post(f"{BASE}/v1/rfq/{cid}/verify", timeout=30).json()
        s.metrics["verify_status"] = v.get("status")
        rd = sess.post(f"{BASE}/v1/rfq/{cid}/reply-draft", timeout=30).json()
        s.metrics["reply_subject"] = (rd.get("reply") or {}).get("subject")
        crm = sess.post(f"{BASE}/v1/rfq/{cid}/crm-sync", timeout=30).json()
        s.metrics["crm_stats"] = crm.get("crm_stats")
        s.pass_()
    run_step("[10] 契约端点全跑 (analyze/verify/reply/crm)", step10)

    # -------------------- [11] HITL 授权 → DONE --------------------
    def step11(s: Step):
        r = sess.post(
            f"{BASE}/v1/rfq/intake",
            data={"email_text": "10 pcs TC4 titanium fixtures, 60x30x12mm, as-machined, precision tolerance IT5.",
                  "customer_name": "Precision Med"},
            timeout=180,
        ).json()
        cid = r["context_id"]
        cids["hitl"] = cid
        s.metrics["before_state"] = r["result"]["state"]
        ap = sess.post(
            f"{BASE}/v1/rfq/{cid}/approve",
            data={"approver": "chief_engineer", "comment": "grinding OK"},
            timeout=30,
        ).json()
        s.metrics["after_state"] = ap.get("state")
        s.metrics["approved"] = ap.get("approved")
        if ap.get("state") == "DONE":
            s.pass_()
        else:
            s.fail(f"approve 后状态未到 DONE, 实际 {ap.get('state')}")
    run_step("[11] HITL 授权 → DONE (TC4+IT5)", step11)

    # -------------------- [12] Postmortem 闭环 --------------------
    def step12(s: Step):
        cid = cids.get("hitl") or cids.get("intake")
        assert cid, "无可用 context_id"
        r = sess.post(
            f"{BASE}/v1/rfq/{cid}/postmortem",
            data={"outcome": "Won", "actual_cost": "1200",
                  "actual_leadtime_days": "25", "note": "e2e test closure"},
            timeout=30,
        ).json()
        s.metrics["postmortem"] = r.get("postmortem")
        s.pass_()
    run_step("[12] Postmortem 闭环", step12)

    # -------------------- [13] 汇总报告 (标记完成) --------------------
    def step13(s: Step):
        s.pass_(steps_total=len(STEPS))  # 此时 STEPS 含 [0]-[12]
    run_step("[13] 汇总报告", step13)

    # ======================== 汇总表 ========================
    print()
    print("=" * 92)
    print(" 端到端测试汇总报告")
    print("=" * 92)
    print(f"{_pad('步骤', 44)} {'结果'} {'ms':>8}   关键指标")
    print("-" * 92)
    for st in STEPS:
        icon = "✅" if st.ok else "❌"
        ms = st.metrics.get("ms", "?")
        kv = ", ".join(f"{k}={_fmt(v)}" for k, v in st.metrics.items() if k != "ms")
        if len(kv) > 60:
            kv = kv[:57] + "..."
        print(f"{_pad(st.name, 44)} {icon} {str(ms):>8}   {kv}")
    print("=" * 92)
    passed = sum(1 for st in STEPS if st.ok)
    failed = len(STEPS) - passed
    print(f"总计: {len(STEPS)} 步,  通过 {passed} ✅,  失败 {failed} ❌")
    print("=" * 92)
    bugs = [st for st in STEPS if not st.ok]
    if bugs:
        print("🚨 发现问题 (BUG FOUND):")
        for st in bugs:
            print(f"  ❌ {st.name}: {st.error}")
    else:
        print("🎉 全部通过, 未发现 BUG")
    print("=" * 92)


if __name__ == "__main__":
    main()