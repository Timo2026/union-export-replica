#!/usr/bin/env python3
"""quote_review.py - 多Agent交叉验证报价"""
import json, time, sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from model_router import ModelRouter

class QuoteReviewer:
    def __init__(self):
        self.router = ModelRouter()
    
    def _ask(self, role: str, prompt: str) -> dict:
        full_prompt = f"你是一个{role}。{prompt}\n只返回JSON。"
        result = self.router.route(full_prompt)
        resp = result.get("response", "")
        if "```" in resp:
            for p in resp.split("```"):
                p = p.strip()
                if p.startswith("{"):
                    resp = p
                    break
        try:
            return json.loads(resp)
        except:
            return {"review": resp[:200], "passed": False, "reason": "解析失败"}
    
    def cross_validate(self, qd: dict) -> dict:
        t0 = time.time()
        mat = self._ask("CNC材料专家",
            f"审查: 材料={qd.get('material','')}, 表面={qd.get('surface_treatment','')}, "
            f"数量={qd.get('quantity',1)}件. 输出JSON: {{\"material_ok\":bool,\"concerns\":[]}}")
        proc = self._ask("CNC工艺专家",
            f"审查: 材料={qd.get('material','')}, 表面={qd.get('surface_treatment','')}, "
            f"尺寸={qd.get('dimensions_mm','')}, 公差={qd.get('tolerance_grade','')}. "
            f"输出JSON: {{\"feasible\":bool,\"difficulty\":\"easy/medium/hard\",\"risks\":[],\"suggestions\":[]}}")
        mk = mat.get("material_ok", True) if isinstance(mat, dict) else True
        fb = proc.get("feasible", True) if isinstance(proc, dict) else True
        if not mk or not fb:
            status = "flagged"
        elif mat.get("concerns") or proc.get("risks"):
            status = "review_needed"
        else:
            status = "approved"
        return {"status": status, "material_review": mat, "process_review": proc, "elapsed": time.time()-t0}

if __name__ == "__main__":
    r = QuoteReviewer().cross_validate({"material":"铝合金6061","surface_treatment":"阳极氧化","quantity":100,"dimensions_mm":"30x20x27mm","tolerance_grade":"IT8"})
    print(f"状态: {r['status']} | 耗时: {r['elapsed']:.1f}s")
