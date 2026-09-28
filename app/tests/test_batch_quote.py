"""test_batch_quote.py — D3 400+常规机加工件批量报价管道 (任务 #32).

管道: bom_rows (BOM xlsx/csv 解析) → parse_spec (规格列 材料+工艺 拆分)
      → quote_bom (逐行喂黄金链 ctrl.run, STEP 几何可得则挂 step_facts)。
铁律: data-stays-local — 真实 BOM 只读, 报告落 data/ (gitignored); 缺文件即 skip。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.file_intake import parse_step  # noqa: F401  (注入点校验)

_BOM = Path("C:/Users/<user>/Music/qianyi/演示/批量报价/常规机加工件BOM.xlsx")
_ASSETS = Path("C:/Users/<user>/Music/qianyi/演示/批量报价/400+常规机加工件")


def _rows():
    """quote_bom 的输入契约 = bom_rows 的规范化输出."""
    return [
        {"idx": 1, "code": "1010001", "name": "戳卡夹外壳", "qty": 4,
         "material": "6061铝合金", "finishes": ["喷砂", "阳极氧化", "喷漆"]},
        {"idx": 2, "code": "1010002", "name": "1号臂座", "qty": 1,
         "material": "304不锈钢", "finishes": ["钝化"]},
    ]


# ---------- parse_spec ----------
def test_parse_spec_splits_material_and_finishes():
    from scripts.batch_quote import parse_spec
    s = parse_spec("6061铝合金+喷砂+阳极氧化+喷漆")
    assert s["material"] == "6061铝合金"
    assert s["finishes"] == ["喷砂", "阳极氧化", "喷漆"]


def test_parse_spec_tolerant_of_junk():
    from scripts.batch_quote import parse_spec
    s = parse_spec(None)
    assert s["material"] == "" and s["finishes"] == []


# ---------- bom_rows ----------
def test_bom_rows_from_csv(tmp_path):
    from scripts.batch_quote import bom_rows
    csv = tmp_path / "bom.csv"
    csv.write_text("序号,物料编码,名称,规格,数量,单价,总价,备注\n"
                   "1,1010001,戳卡夹外壳,6061铝合金+喷砂+阳极氧化,4,,,\n"
                   "2,1010002,1号臂座,304不锈钢+钝化,1,,,\n", encoding="utf-8")
    rows = bom_rows(str(csv))
    assert len(rows) == 2
    assert rows[0]["code"] == "1010001" and rows[0]["qty"] == 4
    assert rows[1]["material"] == "304不锈钢"


def test_bom_rows_over_200_no_truncation(tmp_path):
    """parse_excel 缺省 max_rows=200 会截断 410 行 BOM → bom_rows 必须全量."""
    from scripts.batch_quote import bom_rows
    csv = tmp_path / "big.csv"
    lines = ["序号,物料编码,名称,规格,数量,单价,总价,备注"] + \
            [f"{i},10{i:05d},件{i},6061铝合金,1,,," for i in range(1, 251)]
    csv.write_text("\n".join(lines), encoding="utf-8")
    assert len(bom_rows(str(csv))) == 250


# ---------- quote_bom ----------
class FakeCtrl:
    def __init__(self):
        self.timo = None
        self.calls = []

    def run(self, email_text, customer=None, step_facts=None, context_id=None, **kw):
        self.calls.append({"email_text": email_text, "step_facts": step_facts,
                          "context_id": context_id, "customer": customer})
        price = 12.5 if "6061" in email_text else None
        return {"state": "DONE" if price else "BLOCKED",
                "verification_status": "PASS" if price else "BLOCKED",
                "quote": {"unit_price": price} if price else {},
                "audit_valid": True}


def test_quote_bom_passes_customer_id_for_l2_filter():
    """customer_id 必须透传 → cat_controller quote_anchor 按租户过滤 L2 锚点 (联动审计)."""
    from scripts.batch_quote import quote_bom
    c = FakeCtrl()
    quote_bom(_rows(), c, customer_id="JIEVO")
    assert c.calls[0]["customer"]["customer_id"] == "JIEVO"


def test_quote_bom_prices_and_totals():
    from scripts.batch_quote import quote_bom
    c = FakeCtrl()
    out = quote_bom(_rows(), c)
    assert len(out) == 2 and len(c.calls) == 2
    assert out[0]["unit_price"] == 12.5 and out[0]["total_price"] == 50.0
    assert out[1]["unit_price"] is None and out[1]["state"] == "BLOCKED"
    assert "6061铝合金" in c.calls[0]["email_text"] and "4" in c.calls[0]["email_text"]


def test_quote_bom_attaches_step_when_asset_exists(tmp_path):
    from scripts.batch_quote import quote_bom
    assets = tmp_path / "a"
    assets.mkdir()
    (assets / "1010001-外壳-V1.0.STEP").write_text("ISO-10303", encoding="utf-8")
    c = FakeCtrl()
    seen = {}

    def fake_step(path, timo, material="6061", with_features=True):
        seen["path"] = Path(path).name
        return {"geometry": {"volume_mm3": 1.0}, "_source": "fake"}

    out = quote_bom(_rows(), c, assets_dir=str(assets), step_parser=fake_step)
    assert seen["path"] == "1010001-外壳-V1.0.STEP"
    assert c.calls[0]["step_facts"] is not None
    assert c.calls[1]["step_facts"] is None
    assert out[0]["has_step"] is True and out[1]["has_step"] is False


# ---------- 真实语料 (data-stays-local, 缺文件 skip) ----------
@pytest.mark.skipif(not _BOM.exists(), reason="真实 BOM 不在本机")
def test_real_bom_410_rows_unpriced():
    from scripts.batch_quote import bom_rows
    rows = bom_rows(str(_BOM))
    assert len(rows) == 410
    assert all(r["unit_price"] is None for r in rows)      # 待报价
    assert rows[0]["code"] == "1010001"


@pytest.mark.skipif(not (_BOM.exists() and _ASSETS.exists()), reason="语料不在本机")
def test_real_engine_batch_limit3_golden_chain():
    """3 行走真实离线黄金链: 结构完整 + STEP 几何行必出单价 (确定性引擎)."""
    from bootstrap import build_controller
    from scripts.batch_quote import bom_rows, quote_bom
    rows = [r for r in bom_rows(str(_BOM))
            if list(_ASSETS.rglob(f"{r['code']}-*"))][:3]
    assert len(rows) == 3
    out = quote_bom(rows, build_controller(), assets_dir=str(_ASSETS))
    assert all(o["state"] in ("DONE", "HITL", "BLOCKED", "ARCHIVED") for o in out)
    assert all(o["unit_price"] is not None for o in out)   # 几何驱动定价, 确定性出单价
