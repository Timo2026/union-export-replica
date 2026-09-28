"""batch_quote — BOM 批量报价 Skill (复用 scripts.batch_quote 轮子)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

SKILL_META = {"skill": "batch_quote", "iron_rule": "deterministic"}


def run(ctx, action: str = "quote_bom",
        bom_path: str = "",
        assets_dir: str = "",
        customer_id: str = "",
        out_path: str = "",
        **kwargs) -> Dict[str, Any]:
    if action != "quote_bom":
        return {**SKILL_META, "ok": False, "error": f"未知 action: {action}"}
    if not bom_path:
        return {**SKILL_META, "ok": False,
                "error": "bom_path 必填 (BOM xlsx/csv 路径)"}

    import scripts.batch_quote as bq

    bom_abs = str(Path(bom_path).resolve())     # 内核桥铁律: 绝对路径
    assets_abs = str(Path(assets_dir).resolve()) if assets_dir else None
    if not Path(bom_abs).exists():
        return {**SKILL_META, "ok": False, "error": f"BOM 不存在: {bom_abs}"}

    ctrl = ctx.get_ctrl()
    rows = bq.bom_rows(bom_abs)
    results = bq.quote_bom(rows, ctrl, assets_dir=assets_abs,
                           customer_id=customer_id or None)
    summary = bq.summarize(results)
    out = {**SKILL_META, "ok": True, "summary": summary, "n_rows": len(rows)}
    if out_path:
        out["report_path"] = bq.write_report(
            {"summary": summary, "rows": results}, out_path)
    return out
