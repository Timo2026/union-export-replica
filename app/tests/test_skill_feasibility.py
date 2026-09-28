"""test_skill_feasibility — 精选并入的 feasibility-checker skill (确定性, 不定价)."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import importlib.util

import skills._runtime as rt  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "feasibility_check_tool", _ROOT / "skills" / "feasibility-checker" / "tool.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
run = _mod.run  # noqa: E402


class _Ctx:
    def __init__(self, scratch=None):
        self.scratch = scratch or {}


def _sid():
    # 目录 feasibility-checker → skill_id feasibility_checker
    return "feasibility_checker"


def test_discovered_and_allowlisted():
    disc = rt.discover(force=True)
    assert _sid() in disc, f"skill 未被自动发现: {sorted(disc)}"
    from services.guardrails import TOOL_ALLOWLIST
    assert "feasibility_checker" in TOOL_ALLOWLIST
    assert "feasibility-checker" in TOOL_ALLOWLIST


def test_feasible_case():
    out = run(_Ctx(), length=80, width=60, height=40, weight=2,
              material="6061", tolerance_grade="IT7")
    assert out["ok"] is True
    assert out["feasible"] is True
    assert out["available_equipment"]
    assert out["pricing"] == "none"  # 铁律②: 不产价
    assert "unit_price" not in out and "final_price" not in out


def test_blocked_by_tolerance():
    # IT4 极精, 仅磨床(IT5)最接近, 仍达不到 → 全部阻断
    out = run(_Ctx(), length=80, width=60, height=40, material="6061",
              tolerance_grade="IT4")
    assert out["feasible"] is False
    assert out["issues"] and out["suggestions"]


def test_blocked_by_material_capability():
    # TC4 仅 五轴/磨床/电火花 支持; 给超大尺寸排除五轴 → 至少保留可用
    out = run(_Ctx(), length=80, width=60, height=40, material="TC4",
              tolerance_grade="IT7")
    assert out["ok"] is True
    # TC4 + IT7: 五轴(it6)/磨床(it5)/电火花(it6) 材料OK且公差可达, 尺寸在包络内
    assert "五轴铣" in out["available_equipment"] or out["feasible"]


def test_reads_geometry_from_scratch():
    ctx = _Ctx(scratch={"geometry": {"bounding_box": {"length": 50, "width": 50, "height": 50},
                                     "weight": 1},
                         "rfq": {"material": "6061", "tolerance_grade": "IT7"}})
    out = run(ctx)
    assert out["ok"] is True
    assert out["checked"]["length"] == 50


def test_missing_dims_fails():
    out = run(_Ctx())
    assert out["ok"] is False
    assert "required" in out["error"]
