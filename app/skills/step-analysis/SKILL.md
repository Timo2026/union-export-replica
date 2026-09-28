---
name: step-analysis
description: 解析上传的 STEP 模型，用真实 OCP B-rep 提取 bbox/体积/重量并据材料密度得到几何驱动重量，附加 C1 特征（孔/壁厚/圆角）。当需要几何事实喂给报价或做 DFM 判定时调用。
version: 1
backend: adapters/timo_adapter.py:TimoAdapter.step_geometry / step_features (引擎 .venv OCP)
tool_contract:
  openai_function:
    name: step_analysis
    description: 真实 OCP B-rep 几何解析
    parameters:
      type: object
      properties:
        path: {type: string, description: 本地 STEP 文件绝对路径}
        material: {type: string}
      required: [path]
---

# step-analysis

## 何时用
用户上传 STEP；需要"几何=事实"驱动报价重量/表面积，而非默认值。

## 输入 / 输出
- 入：path、material
- 出：`{bbox_mm, volume_mm3, volume_source:"ocp_brep", weight_kg, surface_area_dm2, max_dim_mm}` + C1 `{hole_count, min_wall_mm, fillets}`

## 契约与失败策略
- 子进程调引擎 `.venv`（OCP）→ 真实 B-rep，非估算。
- C1 特征有 5s 硬超时；大文件返回 `partial`，不抛异常、不阻断（报价回退默认重量）。

## 示例
样本 100×100×260mm STEP → 体积 199098mm³ × 6061(2.7) → weight 0.5376kg → 报价 unit ¥230.32（vs 默认 0.5kg 的 ¥222.8）。
