# -*- coding: utf-8 -*-
from .reasoning_chain import ReasoningChain, StepType
from ..core.material_utils import normalize_material

# (material_lower, surface_substr, is_warning, message)
_RULES = [
    ("304", "阳极氧化", False, "304不锈钢自然钝化，不进行阳极氧化"),
    ("316l", "阳极氧化", False, "316L不锈钢不进行阳极氧化"),
    ("tc4", "镀锌", False, "钛合金不进行镀锌处理"),
    ("钛合金", "镀锌", False, "钛合金不进行镀锌处理"),
    ("6061", "镀锌", False, "铝合金不适合镀锌"),
    ("al6061", "镀锌", False, "铝合金不适合镀锌"),
    ("q235", "阳极氧化", False, "碳钢不进行阳极氧化"),
    ("45钢", "阳极氧化", False, "碳钢不进行阳极氧化"),
    ("6061", "电镀", True, "铝合金可电镀但附着力需预镀"),
    ("al6061", "电镀", True, "铝合金可电镀但附着力需预镀"),
    ("304", "电镀", True, "304可电镀但无必要"),
]

class ConflictChecker:
    def __init__(self, ai_wrapper=None):
        self.ai = ai_wrapper

    def check(self, params):
        params = params or {}
        material = normalize_material(params.get("material", ""), default="")
        surface = str(params.get("surface_treatment") or params.get("surface") or "")
        conflicts = []
        warnings = []
        for m, s, mild, msg in _RULES:
            # 修复缺陷：surface 为空串时 `surface in s` 恒为 True（空串是任意串子串），
            # 导致只要 material 匹配就误判冲突。加 surface 非空守卫。
            if m.lower() == material.lower() and s and surface and (s in surface or surface in s):
                item = {"severity": "warn" if mild else "error",
                        "rule": m + ":" + s, "message": msg}
                if mild:
                    warnings.append(item)
                else:
                    conflicts.append(item)
        valid = len(conflicts) == 0
        return {"valid": valid, "conflicts": conflicts, "warnings": warnings,
                "total_issues": len(conflicts) + len(warnings)}

    def check_with_reasoning(self, params):
        r = self.check(params)
        chain = ReasoningChain("conflict_check", "工艺冲突检测")
        material = params.get("material", "")
        surface = params.get("surface_treatment", "")
        chain.add_input("material", material)
        chain.add_input("surface_treatment", surface)
        if r["conflicts"]:
            for c in r["conflicts"]:
                chain.add_step(StepType.VETO, "禁忌: " + c["rule"], c["message"], confidence=1.0)
        elif r["warnings"]:
            for w in r["warnings"]:
                chain.add_warning(w["message"], w["severity"])
        chain.add_conclusion("工艺冲突结论", confidence=1.0,
                             rationale="可加工" if r["valid"] else "存在工艺冲突，需修正参数")
        chain.finalize()
        r["reasoning_chain"] = chain.to_dict()
        r["reasoning_chain_id"] = chain.chain_id
        return r
