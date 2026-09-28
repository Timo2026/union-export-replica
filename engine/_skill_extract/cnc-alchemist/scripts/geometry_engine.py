#!/usr/bin/env python3
"""
geometry_engine.py - OCC几何建模引擎
自动检测PythonOCC，支持Windows/Linux
"""
import os
import math
from pathlib import Path
from typing import Dict, Optional


def check_occ() -> bool:
    """检测PythonOCC是否可用"""
    try:
        from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCC.Core.STEPControl import STEPControl_Writer
        return True
    except ImportError:
        return False


class GeometryEngine:
    """几何建模引擎，自动适应环境"""

    def __init__(self, output_dir: Optional[str] = None):
        if output_dir is None:
            output_dir = str(Path.home() / '.openclaw/output')
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.has_occ = check_occ()

    def build_and_measure(self, features_dict: Dict) -> Dict:
        """
        构建几何模型并提取物理属性

        Args:
            features_dict: 标准特征字典

        Returns:
            {
                "step_path": str,
                "volume_mm3": float,
                "surface_mm2": float,
                "feature_count": int
            }
        """
        dims = features_dict.get("dimensions", {"W": 80, "H": 80, "D": 30})
        W = dims.get("W", 80)
        H = dims.get("H", 80)
        D = dims.get("D", 30)

        # 如果OCC不可用，使用简化计算
        if not self.has_occ:
            return self._fallback_geometry(W, H, D, features_dict)

        try:
            from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
            from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Cut
            from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
            from OCC.Core.gp import gp_Pnt, gp_Trsf, gp_Vec
            from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
            from OCC.Core.IFSelect import IFSelect_RetDone

            # 构建基体
            base = BRepPrimAPI_MakeBox(W, H, D).Shape()
            shape = base
            feature_count = 1

            # 处理特征
            for feat in features_dict.get("features", []):
                ftype = feat.get("type", "")
                if ftype == "hole":
                    r = feat.get("diameter", 10) / 2
                    depth = feat.get("depth", D)
                    x = feat.get("x", W / 2)
                    y = feat.get("y", H / 2)

                    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder
                    from OCC.Core.gp import gp_Ax2, gp_Dir

                    ax2 = gp_Ax2(gp_Pnt(x, y, 0), gp_Dir(0, 0, 1))
                    cyl = BRepPrimAPI_MakeCylinder(r, depth + 2).Shape()
                    shape = BRepAlgoAPI_Cut(shape, cyl).Shape()
                    feature_count += 1

                elif ftype == "flange_holes":
                    count = feat.get("count", 4)
                    diameter = feat.get("diameter", 10)
                    pcd = feat.get("pcd", W * 0.6)

                    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeCylinder
                    from OCC.Core.gp import gp_Ax2, gp_Dir

                    cx, cy = W / 2, H / 2
                    for i in range(count):
                        angle = 2 * math.pi * i / count
                        x = cx + (pcd / 2) * math.cos(angle)
                        y = cy + (pcd / 2) * math.sin(angle)
                        ax2 = gp_Ax2(gp_Pnt(x, y, -1), gp_Dir(0, 0, 1))
                        cyl = BRepPrimAPI_MakeCylinder(diameter / 2, D + 2).Shape()
                        shape = BRepAlgoAPI_Cut(shape, cyl).Shape()
                        feature_count += 1

            # 导出STEP
            step_path = str(self.output_dir / "output.step")
            writer = STEPControl_Writer()
            writer.Transfer(shape, STEPControl_AsIs)
            writer.Write(step_path)

            # 计算物理属性
            volume_mm3, surface_mm2 = self._calc_physical(shape, W, H, D)

            return {
                "step_path": step_path,
                "volume_mm3": volume_mm3,
                "surface_mm2": surface_mm2,
                "feature_count": feature_count
            }

        except Exception as e:
            print(f"[Geometry] OCC error: {e}")
            return self._fallback_geometry(W, H, D, features_dict)

    def _calc_physical(self, shape, W, H, D):
        """计算物理属性"""
        try:
            from OCC.Core.BRepGProp import brepgprop_VolumeProperties, brepgprop_SurfaceProperties
            from OCC.Core.GProp import GProp_GProps
            vol_props = GProp_GProps()
            brepgprop_VolumeProperties(shape, vol_props)
            volume_mm3 = vol_props.Mass()
            surf_props = GProp_GProps()
            brepgprop_SurfaceProperties(shape, surf_props)
            surface_mm2 = surf_props.Mass()
            return volume_mm3, surface_mm2
        except:
            # Fallback简化计算
            return W * H * D, 2 * (W * H + W * D + H * D)

    def _fallback_geometry(self, W: float, H: float, D: float, features_dict: Dict) -> Dict:
        """OCC不可用时的降级计算"""
        volume_mm3 = W * H * D
        surface_mm2 = 2 * (W * H + W * D + H * D)
        feature_count = 1 + len(features_dict.get("features", []))

        return {
            "step_path": None,
            "volume_mm3": volume_mm3,
            "surface_mm2": surface_mm2,
            "feature_count": feature_count,
            "warning": "OCC unavailable, using simplified calculation"
        }


if __name__ == '__main__':
    engine = GeometryEngine()
    print(f"OCC可用: {engine.has_occ}")

    features = {
        "dimensions": {"W": 120, "H": 120, "D": 30},
        "material": "6061铝合金",
        "features": [
            {"type": "hole", "diameter": 30, "depth": 32, "x": 60, "y": 60}
        ]
    }
    result = engine.build_and_measure(features)
    print(f"结果: {result}")
