"""test_po_parser.py — D1 杰沃 PO PDF 文本抽取 (任务 #30).

实证 (2026-09-20 对 PO-C1066077-621644.pdf 的 pypdf 抽取):
  - 文本型 PDF 可抽; 行项块以 Pos 号开头 "10#712422 CDS240701-A.stp"
  - Material / 材料 : 铝合金  - 6061;  Finish / 后处理 : ...;  Quantity 列
  - "Price net / 单价 :" 之后是**页脚合计**(非行项), 必须截断不解析
铁律: 客户数据 data-stays-local — 测试只用内嵌文本样本, 不读真实文件。
"""
from __future__ import annotations

import pytest

# 真实 PO 的 pypdf 抽取文本样本 (格式保真, 金额已脱敏替换)
SAMPLE_PO = """Production Order / 生产订单  PO-C1066077-621644
供应商 :东莞市杰沃科技有限公司
...
Pos.
项
目Article No
零件号码Quantity
数量Price per.
净价Total
总价
10#712422 CDS240701-A.stp
Material / 材料 : 铝合金  - 6061
Finish / 后处理 : Anodize (Black) / 阳极氧化  ( 黑色 ); 亮光
Msrm. report ordered / 报告 : Standard
Prod. remark / 笔记 :Transportation (Standard) / 运输  ( 标快 )
Client notes / 客户备注 : M37x0.75mm 间距  ( 内螺纹 )
Tolerance/ 公差 :
Part Marking / 零件标记 :1 ¥ 298.94 ¥ 298.94
20#712428 CDS240701-B.stp
Material / 材料 : 铝合金  - 6061
Finish / 后处理 : Anodize (Black) / 阳极氧化  ( 黑色 ); 亮光
Tolerance/ 公差 :
Part Marking / 零件标记 :1 ¥ 251.06 ¥ 251.06
# Standard Measurement Protocol 1 ¥ 0.00 ¥ 0.00
Price net / 单价 :
¥ 550.00
收到发票后 45 天付款
"""


def test_parse_po_text_extracts_po_id_and_items():
    from services.po_parser import parse_po_text
    r = parse_po_text(SAMPLE_PO)
    assert r["po_id"] == "PO-C1066077-621644"
    assert len(r["items"]) == 2                       # SMP 服务行 (pos=空) 不算零件行
    a, b = r["items"]
    assert a["article"] == "712422" and a["part"] == "CDS240701-A.stp"
    assert a["qty"] == 1 and a["unit_price"] == 298.94
    assert b["unit_price"] == 251.06


def test_parse_po_text_item_fields_material_surface():
    from services.po_parser import parse_po_text
    r = parse_po_text(SAMPLE_PO)
    a = r["items"][0]
    assert a["material"] == "6061"                    # 铝合金 - 6061 → 提取合金号
    assert "阳极氧化" in a["surface"]
    assert r["footer_total"] == 550.00                # 页脚合计单独抽出, 不进行项


def test_parse_po_text_pypdf_artifact_spacing_normal():
    """pypdf 双空格等 artifact 不破坏解析 (真实文本里 '铝合金  -  6061' 有双空格)。"""
    from services.po_parser import parse_po_text
    noisy = SAMPLE_PO.replace("1 ¥ 298.94 ¥ 298.94", "1  ¥  298.94  ¥  298.94")
    r = parse_po_text(noisy)
    assert r["items"][0]["unit_price"] == 298.94


def test_parse_po_text_no_items_returns_empty():
    from services.po_parser import parse_po_text
    r = parse_po_text("随机文本没有表格")
    assert r["items"] == [] and r["po_id"] is None


def test_parse_po_text_skips_service_rows():
    """'# Standard Measurement Protocol …' 服务行 (无 pos/article) 不进 items。"""
    from services.po_parser import parse_po_text
    r = parse_po_text(SAMPLE_PO)
    assert len(r["items"]) == 2
    assert all(i["article"] and i["article"].isdigit() for i in r["items"])


def test_parse_po_text_short_customer_code():
    """实证 PO-C984249-631069: 客户代码 6 位也要匹配 (真实语料 129 个中 1 个)。"""
    from services.po_parser import parse_po_text
    r = parse_po_text("Production Order / 生产订单  PO-C984249-631069\n" + SAMPLE_PO.split("\n", 1)[1])
    assert r["po_id"] == "PO-C984249-631069"


def test_parse_po_file_missing_returns_error(tmp_path):
    from services.po_parser import parse_po_file
    r = parse_po_file(str(tmp_path / "missing.pdf"))
    assert r["ok"] is False
