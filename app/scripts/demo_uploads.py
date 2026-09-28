"""demo_uploads.py — 演示"所有数据上传端口"功能模块.

优先命中已启动的 :8900 服务; 未启动则用 FastAPI TestClient 在进程内演示 (自包含)。
展示: 每种模态上传端口 + 统一 intake(email+真STEP) + 契约端点 + HITL 授权。
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
_S = _ROOT / "data" / "samples"


def _live(base="http://127.0.0.1:8900"):
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    if _live():
        print("模式: 命中已启动的 live API :8900\n")
        import requests
        B = "http://127.0.0.1:8900"
        sess = requests.Session()
        post = lambda u, **kw: sess.post(B + u, timeout=120, **kw).json()
        get = lambda u: sess.get(B + u, timeout=30).json()
        up = lambda kind, path, **d: post(f"/v1/upload/{kind}",
                                          files={"file": open(path, "rb")}, data=d)
    else:
        print("模式: :8900 未启动 → 进程内 TestClient 演示\n")
        from fastapi.testclient import TestClient
        from services.api_server import app
        _c = TestClient(app)
        post = lambda u, **kw: _c.post(u, timeout=120, **kw).json()
        get = lambda u: _c.get(u, timeout=30).json()
        up = lambda kind, path, **d: post(f"/v1/upload/{kind}",
                                          files={"file": open(path, "rb")}, data=d)

    print("=" * 70)
    print(" 全模态上传端口演示")
    print("=" * 70)

    print("\n[1] EMAIL 端口 (.eml → stdlib 解析)")
    e = up("email", str(_S / "sample_rfq.eml"))
    print("   subject:", e.get("subject"), "| src:", e.get("_source"))

    print("\n[2] STEP 端口 (真实 OCP B-rep 几何)")
    s = up("step", str(_S / "sample_part.STEP"), material="6061")
    g = s.get("geometry", {})
    print(f"   bbox={g.get('bbox_mm')} vol={g.get('volume_mm3')}mm³ "
          f"weight={g.get('weight_kg')}kg src={g.get('volume_source')}")
    f = s.get("features", {})
    print(f"   C1 特征: ok={f.get('ok')} holes={f.get('hole_count')} partial={f.get('partial')}")

    print("\n[3] EXCEL/CSV 端口")
    csv_b = b"material,qty,surface\n6061,50,anodizing\n304,20,passivation\n"
    x = post("/v1/upload/excel", files={"file": ("bom.csv", csv_b, "text/csv")})
    print("   rows:", x.get("n_rows"), "| src:", x.get("_source"))

    print("\n[4] AUDIO 端口 (funasr ASR; 离线显式 MOCK)")
    a = post("/v1/upload/audio", files={"file": ("v.wav", b"RIFF\x00\x00WAVEfmt ", "audio/wav")},
             data={"mock_text": "关键尺寸可放宽到 0.05 毫米"})
    print("   src:", a.get("_source"), "| mock:", a.get("_mock"))

    print("\n[5] 统一 INTAKE (email + 真STEP 一次收全 → 黄金链)")
    files = {"email_file": open(_S / "sample_rfq.eml", "rb"),
             "step_file": open(_S / "sample_part.STEP", "rb")}
    r = post("/v1/rfq/intake", files=files,
             data={"customer_name": "Northwind Robotics", "contact_name": "Alice",
                   "country": "US", "material_hint": "6061"})
    cid = r["context_id"]; res = r["result"]
    print("   context_id:", cid)
    print("   uploads:", r.get("parsed_uploads"))
    print(f"   state={res['state']} verify={res['verification_status']} "
          f"unit={res['quote'].get('unit_price')} final={res['quote'].get('final_price')} "
          f"engine={res['engine_source']} audit_ok={res['audit_valid']}")

    print("\n[6] 契约端点 analyze/quote/verify/reply/crm")
    print("   analyze dfm.valid:", post(f"/v1/rfq/{cid}/analyze")["dfm"]["valid"])
    print("   verify:", post(f"/v1/rfq/{cid}/verify")["status"])
    print("   reply:", post(f"/v1/rfq/{cid}/reply-draft")["reply"]["subject"][:55])
    print("   crm:", post(f"/v1/rfq/{cid}/crm-sync").get("crm_stats"))

    print("\n[7] HITL 授权推进 (TC4+IT5 → HITL → approve → DONE)")
    r2 = post("/v1/rfq/intake",
              data={"email_text": "10 pcs TC4 titanium fixtures, 60x30x12mm, as-machined, precision tolerance IT5.",
                    "customer_name": "Precision Med"})
    c2 = r2["context_id"]
    print("   before:", get(f"/v1/rfq/{c2}")["state"])
    ap = post(f"/v1/rfq/{c2}/approve", data={"approver": "chief_engineer", "comment": "grinding OK"})
    print("   after approve:", ap.get("state"), "approved:", ap.get("approved"))

    print("\n" + "=" * 70)
    print(" 演示完成: 所有数据模态均有上传端口, 统一 intake 跑通真实黄金链 ✅")
    print("=" * 70)


if __name__ == "__main__":
    main()
