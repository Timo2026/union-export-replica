#!/usr/bin/env python3
"""
quote_engine.py - 工业级报价引擎
从geometry_engine获取物理数据，自动加载成本库
"""
import json
import os
from pathlib import Path
from typing import Dict, Optional


DEFAULT_COEFFS = {
    "material_price_per_m3": {
        "6061铝合金": 25000,
        "304不锈钢": 52000,
        "不锈钢/304": 52000,
        "碳钢/45#": 12000,
        "45#钢": 12000,
        "黄铜/H62": 45000
    },
    "surface_price_per_m2": {
        "阳极氧化": 150,
        "导电氧化": 100,
        "钝化": 80,
        "镀镍": 200,
        "镀锌": 120,
        "发黑": 40,
        "喷塑": 100,
        "无": 0
    },
    "feature_base_cost": 12.5,
    "setup_cost": 150,
    "tolerance_factor": {
        "IT6": 2.0, "IT7": 1.7, "IT8": 1.4, "IT9": 1.2,
        "IT10": 1.0, "IT11": 0.85, "IT12": 0.7
    },
    "roughness_factor": {
        "0.8": 1.6, "1.6": 1.3, "3.2": 1.0, "6.3": 0.8
    }
}


class QuoteEngine:
    """工业级报价引擎，自动加载成本库"""

    def __init__(self, db_path: Optional[str] = None):
        self.db = self._load_coeffs(db_path)

    def _load_coeffs(self, path: Optional[str]) -> Dict:
        """加载成本系数库"""
        coeffs = DEFAULT_COEFFS.copy()

        # 尝试从文件加载
        if path and os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                coeffs.update(loaded)
            except Exception as e:
                print(f"[Quote] Load coeffs error: {e}")

        # 尝试从data目录加载
        data_path = Path(__file__).parent.parent / 'data' / 'material_db.json'
        if data_path.exists():
            try:
                with open(data_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                coeffs.update(loaded)
            except:
                pass

        return coeffs

    def _normalize_material(self, material: str) -> str:
        """标准化材料名称"""
        material = material.lower()
        if "6061" in material or "铝合金" in material:
            return "6061铝合金"
        if "304" in material or "不锈钢" in material:
            return "304不锈钢"
        if "45" in material or "碳钢" in material:
            return "碳钢/45#"
        if "黄铜" in material or "h62" in material:
            return "黄铜/H62"
        return material

    def calculate(self, features_dict: Dict, geometry_metrics: Dict) -> Dict:
        """
        计算报价

        Args:
            features_dict: 特征字典
            geometry_metrics: 几何数据 {volume_mm3, surface_mm2, feature_count}

        Returns:
            报价明细
        """
        material = features_dict.get("material", "6061铝合金")
        tolerance = features_dict.get("tolerance", "IT10")
        ra = features_dict.get("ra", 3.2)
        surface = features_dict.get("surface_treatment", "无")
        quantity = max(int(features_dict.get("quantity", 1)), 1)

        # 物理数据
        volume_m3 = geometry_metrics.get("volume_mm3", 0) / 1e9
        surface_m2 = geometry_metrics.get("surface_mm2", 0) / 1e6
        feature_count = geometry_metrics.get("feature_count", 1)

        # 标准化材料
        mat_key = self._normalize_material(material)

        # 1. 材料费
        mat_price = self.db["material_price_per_m3"].get(mat_key, 25000)
        material_cost = volume_m3 * mat_price

        # 2. 表面处理费
        surf_price = self.db["surface_price_per_m2"].get(surface, 0)
        surface_cost = surface_m2 * surf_price

        # 3. 机加费
        machining_base = feature_count * self.db["feature_base_cost"]
        tol_factor = self.db["tolerance_factor"].get(tolerance, 1.0)
        ra_factor = self.db["roughness_factor"].get(str(ra), 1.0)
        machining_cost = machining_base * tol_factor * ra_factor

        # 4. 装夹费
        setup_cost = self.db["setup_cost"]

        # 5. 合计
        subtotal = material_cost + surface_cost + machining_cost + setup_cost
        total = subtotal * quantity

        return {
            "material_cost_rmb": round(material_cost, 2),
            "surface_cost_rmb": round(surface_cost, 2),
            "machining_cost_rmb": round(machining_cost, 2),
            "setup_cost_rmb": setup_cost,
            "unit_price_rmb": round(subtotal, 2),
            "total_rmb": round(total, 2),
            "quantity": quantity,
            "physical_basis": {
                "volume_mm3": round(geometry_metrics.get("volume_mm3", 0), 1),
                "surface_mm2": round(geometry_metrics.get("surface_mm2", 0), 1),
                "feature_count": feature_count,
                "tolerance": tolerance,
                "ra": ra
            }
        }


if __name__ == '__main__':
    engine = QuoteEngine()

    features = {
        "material": "6061铝合金",
        "dimensions": {"W": 120, "H": 120, "D": 30},
        "tolerance": "IT10",
        "ra": 3.2,
        "surface_treatment": "阳极氧化",
        "quantity": 10,
        "features": []
    }

    geometry = {
        "volume_mm3": 120 * 120 * 30,
        "surface_mm2": 2 * (120 * 120 + 120 * 30 + 120 * 30),
        "feature_count": 1
    }

    quote = engine.calculate(features, geometry)
    print(f"报价结果:")
    for k, v in quote.items():
        print(f"  {k}: {v}")
