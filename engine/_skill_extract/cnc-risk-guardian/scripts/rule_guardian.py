#!/usr/bin/env python3
"""
rule_guardian.py - CNC硬规则守卫
来源: cat-eatmagic硬规则层模式
功能: 报价输出前拦截，检查材料×工艺禁忌，模型无法推翻
"""
import os
import sys
import yaml
import json
import re
from typing import Dict, List, Optional, Tuple

RULES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rules")

class RuleGuardian:
    """硬规则守卫 - 拦截致命工艺错误"""
    
    def __init__(self):
        self.constraints = self._load_constraints()
        self.violations = []
    
    def _load_constraints(self) -> dict:
        """加载YAML禁忌规则"""
        path = os.path.join(RULES_DIR, "cnc_constraints.yaml")
        if not os.path.exists(path):
            print(f"⚠️ 规则文件不存在: {path}")
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    
    def check_material_heat_treatment(self, material: str, process: str) -> Optional[dict]:
        """检查材料×热处理禁忌"""
        for rule in self.constraints.get("material_heat_treatment_forbidden", []):
            if rule["material"] in material and rule["process"] in process:
                return rule
        return None
    
    def check_material_surface(self, material: str, surface: str) -> Optional[dict]:
        """检查材料×表面处理禁忌"""
        for rule in self.constraints.get("material_surface_forbidden", []):
            if rule["material"] in material and rule["surface"] in surface:
                return rule
        return None
    
    def check_wall_thickness(self, material: str, wall_thickness: float) -> Optional[dict]:
        """检查壁厚下限"""
        for rule in self.constraints.get("wall_thickness_limits", []):
            if rule["material"] in material and wall_thickness < rule["min_wall"]:
                return rule
        return None
    
    def check_tolerance(self, material: str, tolerance_grade: str) -> Optional[dict]:
        """检查公差等级×材料限制"""
        # 提取IT数字
        m = re.search(r'IT(\d+)', tolerance_grade)
        if not m:
            return None
        it_num = int(m.group(1))
        
        for rule in self.constraints.get("tolerance_material_limits", []):
            if rule["material"] in material:
                m2 = re.search(r'IT(\d+)', rule["max_tolerance_grade"])
                if m2 and it_num > int(m2.group(1)):
                    return rule
        return None
    
    def get_substitution(self, material: str, forbidden: str) -> Optional[str]:
        """获取替代工艺建议"""
        for sub in self.constraints.get("substitution_suggestions", []):
            if sub["material"] in material and sub["forbidden"] in forbidden:
                return sub["suggest"]
        return None
    
    def guard(self, quote_data: dict) -> dict:
        """
        主拦截函数 - 在报价输出前调用
        返回: {status, violations, risk_notes, confidence_adjusted}
        """
        self.violations = []
        
        material = quote_data.get("material", "")
        surface = quote_data.get("surface_treatment", "")
        heat_treatment = quote_data.get("heat_treatment", "")
        wall_thickness = quote_data.get("min_wall_thickness", 999.0)
        tolerance = quote_data.get("tolerance_grade", "")
        
        # 检查所有禁忌
        checks = [
            ("heat_treatment", self.check_material_heat_treatment(material, heat_treatment)),
            ("surface", self.check_material_surface(material, surface)),
            ("wall_thickness", self.check_wall_thickness(material, wall_thickness)),
            ("tolerance", self.check_tolerance(material, tolerance)),
        ]
        
        for check_type, violation in checks:
            if violation:
                v = {
                    "type": check_type,
                    "material": material,
                    "violation": violation,
                    "suggestion": None,
                }
                # 查找替代建议
                if check_type == "surface":
                    v["suggestion"] = self.get_substitution(material, violation["surface"])
                elif check_type == "heat_treatment":
                    v["suggestion"] = self.get_substitution(material, violation["process"])
                self.violations.append(v)
        
        # 判定
        has_fatal = any(v["violation"]["severity"] == "FATAL" for v in self.violations)
        has_warning = any(v["violation"]["severity"] == "WARNING" for v in self.violations)
        
        if has_fatal:
            status = "blocked"
            confidence = 0.0
        elif has_warning:
            status = "warned"
            confidence = quote_data.get("confidence", 1.0) * 0.7
        else:
            status = "passed"
            confidence = quote_data.get("confidence", 1.0)
        
        risk_notes = []
        for v in self.violations:
            reason = v['violation'].get('reason', v['violation'].get('note', '未知违规'))
            note = f"[{v['violation']['severity']}] {reason}"
            if v.get("suggestion"):
                note += f" -> 建议替代: {v['suggestion']}"
            risk_notes.append(note)
        
        return {
            "status": status,          # blocked / warned / passed
            "violations": self.violations,
            "risk_notes": risk_notes,
            "confidence_adjusted": confidence,
            "original_confidence": quote_data.get("confidence", 1.0),
        }
    
    def guard_batch(self, quotes: list) -> list:
        """批量拦截"""
        return [self.guard(q) for q in quotes]


# === CLI入口 ===
if __name__ == "__main__":
    guardian = RuleGuardian()
    
    # 测试用例
    test_cases = [
        {"material": "铝合金6061", "surface_treatment": "发黑", "heat_treatment": "", "min_wall_thickness": 1.0, "tolerance_grade": "IT7"},
        {"material": "304不锈钢", "surface_treatment": "镀锌", "heat_treatment": "", "min_wall_thickness": 0.5, "tolerance_grade": "IT7"},
        {"material": "304不锈钢", "surface_treatment": "电解抛光", "heat_treatment": "淬火", "min_wall_thickness": 0.5, "tolerance_grade": "IT7"},
        {"material": "铝合金6061", "surface_treatment": "阳极氧化", "heat_treatment": "", "min_wall_thickness": 1.5, "tolerance_grade": "IT7"},
    ]
    
    print("=== HardGuard 硬规则守卫测试 ===\n")
    for i, tc in enumerate(test_cases):
        result = guardian.guard(tc)
        print(f"测试{i+1}: {tc['material']} / {tc.get('surface_treatment','')} / {tc.get('heat_treatment','')}")
        print(f"  状态: {result['status']}")
        if result["risk_notes"]:
            for note in result["risk_notes"]:
                print(f"  ⚠️ {note}")
        else:
            print(f"  ✅ 通过")
        print()
