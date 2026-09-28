# -*- coding: utf-8 -*-
import math
from .step_generator import DENSITY


def step_to_stl_ocp(step_path, stl_path, deflection=0.5):
    """用已安装的 OCP/OpenCASCADE 把 STEP 三角化并导出 STL。

    不依赖 cascadion/cadquery，直接使用 OCP 的 STEPControl_Reader +
    BRepMesh_IncrementalMesh + StlAPI_Writer。

    返回 True 表示成功写出 STL，False 表示失败。
    """
    try:
        from OCP.STEPControl import STEPControl_Reader
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.StlAPI import StlAPI_Writer

        reader = STEPControl_Reader()
        reader.ReadFile(step_path)
        reader.TransferRoots()
        shape = reader.OneShape()
        if shape.IsNull():
            print('[step_to_stl_ocp] null shape', flush=True)
            return False

        mesh = BRepMesh_IncrementalMesh(shape, deflection)
        mesh.Perform()

        writer = StlAPI_Writer()
        ok = writer.Write(shape, stl_path)
        print(f'[step_to_stl_ocp] Write return={ok}', flush=True)
        return bool(ok)
    except Exception as e:
        print(f'[step_to_stl_ocp] failed: {e}', flush=True)
        return False


def extract_bbox_from_step(file_path):
    bbox = {"dim_x": 100, "dim_y": 100, "dim_z": 20,
            "volume_mm3": 200000, "volume_source": "estimate",
            "error": None, "detected_format": "stl/step", "detail": "",
            "suggestions": [], "file_size": 0}
    try:
        import os
        bbox["file_size"] = os.path.getsize(file_path)
    except Exception:
        pass

    # 路径1：尝试 trimesh 加载（需要 cascadion/OCC 支持 STEP）
    # 注意：cascadion 未安装时 trimesh.load 会挂起，必须先检查
    _trimesh_available = False
    try:
        import trimesh
        # 检查 cascadion 是否可用（trimesh 的 STEP 加载器依赖它）
        try:
            import cascadion  # noqa: F401
            _trimesh_available = True
        except ImportError:
            pass  # cascadion 未安装，跳过 trimesh 路径
    except ImportError:
        pass  # trimesh 未安装

    if _trimesh_available:
        try:
            m = trimesh.load(file_path, force="mesh")
            if m is not None and hasattr(m, 'vertices') and len(m.vertices) > 0:
                # 单位修正: cascadion/OCC 输出米制，STEP标准毫米
                try:
                    fix_step_unit_scale(m, file_path)
                except Exception:
                    pass
                ext = m.extents
                bbox["dim_x"] = round(float(ext[0]), 2)
                bbox["dim_y"] = round(float(ext[1]), 2)
                bbox["dim_z"] = round(float(ext[2]), 2)
                if getattr(m, "is_watertight", False) and getattr(m, "volume", None):
                    bbox["volume_mm3"] = abs(m.volume)
                    bbox["volume_source"] = "trimesh_volume"
                else:
                    bbox["volume_mm3"] = ext[0] * ext[1] * ext[2]
                    bbox["volume_source"] = "bbox_estimate"
                return bbox
        except Exception:
            pass  # trimesh 失败，尝试 cadquery fallback

    # 路径2：优先使用已安装的 OCP/OpenCASCADE 直接解析 B-Rep。
    try:
        from OCP.BRepBndLib import BRepBndLib
        from OCP.BRepGProp import BRepGProp
        from OCP.Bnd import Bnd_Box
        from OCP.GProp import GProp_GProps
        from OCP.STEPControl import STEPControl_Reader

        reader = STEPControl_Reader()
        if reader.ReadFile(file_path) != 1:
            raise ValueError("OCP STEPControl_Reader.ReadFile failed")
        if reader.TransferRoots() == 0:
            raise ValueError("OCP STEPControl_Reader.TransferRoots failed")
        shape = reader.OneShape()
        if shape.IsNull():
            raise ValueError("OCP returned a null shape")

        # OCP 静态方法以 _s 后缀暴露；AddOptimal_s 比 Add_s 包络更紧。
        box = Bnd_Box()
        add_fn = getattr(BRepBndLib, "AddOptimal_s", None) or getattr(BRepBndLib, "Add_s")
        add_fn(shape, box)
        xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
        props = GProp_GProps()
        vol_fn = getattr(BRepGProp, "VolumeProperties_s", None)
        if vol_fn is None:
            raise ValueError("OCP BRepGProp.VolumeProperties_s not available")
        vol_fn(shape, props)
        volume = abs(float(props.Mass()))
        bbox["dim_x"] = round(float(xmax - xmin), 2)
        bbox["dim_y"] = round(float(ymax - ymin), 2)
        bbox["dim_z"] = round(float(zmax - zmin), 2)
        bbox["volume_mm3"] = volume
        bbox["volume_source"] = "ocp_brep"
        print(f'[step_parser] OCP success: {bbox["dim_x"]}x{bbox["dim_y"]}x{bbox["dim_z"]}', flush=True)
        return bbox
    except Exception as ocp_error:
        print(f'[step_parser] OCP failed: {ocp_error}', flush=True)

    # 路径3：cadquery fallback（可选高层封装）。
    try:
        print(f'[step_parser] cadquery fallback: {file_path}', flush=True)
        import cadquery as cq
        shape = cq.importers.importStep(file_path)
        val = shape.val()
        bb = val.BoundingBox()
        bbox["dim_x"] = round(float(bb.xlen), 2)
        bbox["dim_y"] = round(float(bb.ylen), 2)
        bbox["dim_z"] = round(float(bb.zlen), 2)
        bbox["volume_mm3"] = abs(val.Volume())
        bbox["volume_source"] = "cadquery_brep"
        return bbox
    except Exception as cadquery_error:
        print(f'[step_parser] cadquery failed: {cadquery_error}', flush=True)
        bbox["error"] = (
            f"STEP解析失败(trimesh+OCP+cadquery均失败): "
            f"{type(cadquery_error).__name__}: {cadquery_error}"
        )
        bbox["volume_source"] = "fallback_all_failed"
        return bbox

def estimate_volume_from_bbox(bbox):
    if not bbox:
        return 0.0
    try:
        v = float(bbox.get("volume_mm3") or 0)
        if v > 0:
            return v
        return float(bbox.get("dim_x", 0)) * float(bbox.get("dim_y", 0)) * float(bbox.get("dim_z", 0))
    except Exception:
        return 0.0

def get_material_density(material):
    return DENSITY.get(material, 2.8)


def fix_step_unit_scale(loaded, file_path):
    """修正 STEP 文件的米制/毫米制单位（cascadio/OCC 的 trimesh loader 默认输出米）。

    用 cadquery.importStep 作为权威尺寸源（直接返回毫米），
    比较 trimesh extents 与 cadquery BoundingBox，若相差 ~1000 倍则缩放。
    cadquery 不可用时回退到阈值法（extents.max() < 1.0 → ×1000）。

    参数:
        loaded: trimesh.load() 返回的 mesh/Scene（会原地缩放）
        file_path: STEP 文件路径
    返回:
        scale_factor: 实际应用的缩放倍数（1.0 表示未缩放）
    """
    try:
        extents = loaded.extents
    except Exception:
        return 1.0
    if extents is None or len(extents) == 0 or extents.max() <= 0:
        return 1.0

    # 优先：cadquery 权威校验
    try:
        import cadquery as cq
        cq_shape = cq.importers.importStep(file_path)
        cq_val = cq_shape.val()
        cq_bb = cq_val.BoundingBox()
        cq_max_dim = max(cq_bb.xlen, cq_bb.ylen, cq_bb.zlen)
        if cq_max_dim > 0:
            ratio = cq_max_dim / extents.max()
            # ~1000 倍 = 米→毫米；~100 倍 = 厘米→毫米（罕见）；~1 倍 = 已正确
            if 500 < ratio < 2000:
                loaded.apply_scale(ratio)
                return ratio
            elif 50 < ratio < 200:
                loaded.apply_scale(ratio)
                return ratio
            return 1.0  # 尺寸一致，无需缩放
    except Exception:
        pass

    # 回退：阈值法（cadquery 不可用时）
    if extents.max() < 1.0:
        loaded.apply_scale(1000.0)
        return 1000.0
    return 1.0
