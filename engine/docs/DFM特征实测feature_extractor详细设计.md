# C1 DFM 特征实测（feature_extractor）详细设计

> 版本: v1.0 | 日期: 2026-09-17 | 状态: 待评审
> 目标零件验证样例: `4xOdRrJv2S_jsLlUVlwNOeYA` = Custom-Dual_Color-Adaption_Board.step (6061, 450×115.18×10, IT7, 三轴CNC)

---

## 0. 目标与边界（先说清楚不做什么）

**做**：只读实测 —— 遍历 STEP B-rep 拓扑，提取孔特征（孔径/孔深/深径比）、最小壁厚（近似值+置信度）、圆角/内直角，闭合 DFM 人工确认项 4 项中的 3 项。**装夹基准是工艺决策，仍留人工确认。**

**不做**：
- 不修改客户原始 STEP（报价/工艺系统擅改客户图纸属越权，溯源断裂）
- 不做几何写入（倒角/工艺台/阶梯孔等 C2 内容，待 C1 实测后另议范围）
- 不引入新依赖（OCP/trimesh/cadquery 均已在 requirements-ocp.txt / requirements.txt 中）

**降级承诺**：任何异常 → features 缺失 → 系统行为与现状完全一致（向后兼容）。

---

## 1. 现状基线（代码证据，file:line 已逐条核实）

| 位置 | 现状 | 后果 |
|---|---|---|
| `src/runtime/step_parser.py` L88-121 | OCP 只做 `BRepBndLib.AddOptimal_s`（bbox）+ `BRepGProp.VolumeProperties_s`（体积），**无 `TopExp_Explorer` 拓扑遍历** | 只知道盒子大小，不知道孔在哪 |
| `src/runtime/part_analysis.py` L30, L89-110 | `min_wall/hole_d/hole_depth` 仅来自 `extras` 参数 | 无实测来源 |
| `app/main.py` L1739-1744 | DFM 端点 extras 仅取 request body 手填字段 | UI 按钮发空 body |
| `app/static/index_merged.html` L988 | UI `analyzePart` 固定发 `body:'{}'` | extras 恒为 None |
| `app/main.py` L3494, L3513 | 聊天路径直接 `rule_dfm(trusted_ctx, {})` | extras 恒空 |

**根因链**：五处数据源都不给实测特征 → `missing_review_fields()` 恒非空 → `dfm_score=None`、`status=needs_review` 永远成立。这不是规则写错，是系统从未真正"看"过几何。

---

## 2. 新增模块 `src/runtime/feature_extractor.py`（约 300 行）

### 2.1 算法选型（OCP API 级）

**读入**（复用 step_parser 已验证路径，规避 cascadio 米制陷阱）：
- `STEPControl_Reader` → `ReadFile` → `TransferRoots()` → `OneShape()`
- OCP 直读 STEP 为毫米制（STEP 标准单位），无 `fix_step_unit_scale` 的缩放问题
- 单位防御：提取的 bbox 与现有 `extract_bbox_from_step()` 结果交叉比对，偏差 >2% → `unit_suspect=true` 并降置信度

**拓扑遍历**：
- `TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)` 逐面
- `TopExp.MapShapes_s(shape, TopAbs_FACE, TopTools_IndexedMapOfShape)` 去重（避免共享面重复计数）
- ⚠️ **必须向下转型**：`exp.Current()` 返回 `TopoDS_Shape`（基类），需先 `TopoDS.Face_s(exp.Current())` 转型为 `TopoDS_Face` 再构造 adaptor，否则 `TypeError: incompatible constructor arguments`（2026-09-17 已用真实法兰盘件实测验证）

**面分类**（`BRepAdaptor_Surface(TopoDS.Face_s(face)).GetType()`）：
- `GeomAbs_Cylinder` → 孔 / 外圆柱候选
- `GeomAbs_Torus` → 过渡圆角（内凹 R）
- `GeomAbs_Plane` / `GeomAbs_Cone` → 平面/锥面（沉头孔拆段用）
- `GeomAbs_BSplineSurface` 等 → 自由曲面，标记 `freeform_faces>0`，整体置信度降级

**孔提取**（`GeomAbs_Cylinder` 分支）：
| 量 | 方法 | API |
|---|---|---|
| 孔径 d | 圆柱半径×2 | `BRepAdaptor_Surface.Cylinder().Radius()` |
| 轴向 | 圆柱轴方向 | `.Axis().Direction()`（gp_Dir） |
| 孔深 | 面 bbox 沿轴向投影长度，与 UV 的 V 参数范围交叉校验 | `BRepBndLib.Add_s(face)` 投影 + `BRepTools.UVBounds_s` |
| 内孔 vs 外圆柱 | 双判据：面朝向（`face.Orientation()==TopAbs_REVERSED`）+ 面采样点法向与（点−轴线）方向点积为负 | `BRepGProp.FaceProperties_s` 采样 或 `BRepAdaptor_Surface` 求法向 |
| 通孔/盲孔 | \|孔深 − 板厚(bbox最小边)\| < 0.05mm → through | bbox 来自读入时顺带计算 |
| 阶梯/沉头孔 | 轴共线（方向点积≈±1 且轴线距离 < 容差）+ 半径不同 → 聚簇为分段孔组 | 自实现，容差 0.01mm |
| 螺纹底孔 | B-rep 中螺纹通常建模为光圆柱 → 输出 `thread_suspect` 标记，不冒充螺纹参数 | — |

**圆角与内直角**：
- `GeomAbs_Torus` → `gp_Torus.MinorRadius()` 收集 → `min_fillet_r`
- 内直角证据：相邻平面夹角≈90° 且两平面间无过渡面（Torus/圆柱过渡）→ 计数 `right_angle_edges`（供 dfm_checker「内直角无法直接CNC加工」warn 规则做实测依据）

**最小壁厚**（近似值，明确标注方法与置信度，不冒充实测精确值）：
- 方案A（采用）：复用 `step_to_stl_ocp` 网格化（deflection 收紧到 0.2）→ **纯 numpy 手写点到三角面距离**（⚠️ 禁止依赖 `trimesh.proximity.ProximityQuery` / `convex_hull`，二者内部依赖 scipy，本环境未安装会静默失败不报错）→ 采样点取**实体内部点**（非包围盒边缘/表面，否则距离恒 0）→ 取 0.5% 分位作为 `min_wall_mm.value`
- 方案B（备选，A 失败时）：体素腐蚀法，分辨率 0.5mm（450×115×10 → ≈4.1M 体素，内存可接受）
- 输出格式：`min_wall_mm: {value: 8.6, method: "mesh_proximity", confidence: "approximate±0.2"}`

**性能预算**：全遍历 O(面数)。480KB STEP 预估数百~数千面，目标 <2s；硬超时 5s → 返回已提取的部分结果 + `partial=true`。

### 2.2 输出 Schema（features）

```json
{
  "holes": [
    {"d_mm": 5.0, "depth_mm": 10.0, "ld_ratio": 2.0, "through": true,
     "axis": [0,0,1], "thread_suspect": false, "segment_group": "g1"}
  ],
  "hole_summary": {"count": 12, "min_d_mm": 3.2, "max_ld_ratio": 2.0,
                   "by_diameter": {"3.2": 8, "5.0": 4}},
  "min_wall_mm": {"value": 8.6, "method": "mesh_proximity", "confidence": "approximate±0.2"},
  "fillets": {"min_r_mm": 2.0, "torus_count": 6},
  "right_angle_edges": 4,
  "plane_area_dm2": 12.9,
  "stats": {"face_count": 342, "cyl_face_count": 24, "duration_ms": 850, "partial": false},
  "confidence": "high",
  "warnings": ["thread_suspect: 3 个光圆柱孔可能为螺纹底孔，需按图纸确认规格"],
  "unknowns": []
}
```

判定映射（喂给 `rule_dfm`）：`hole_d = min(holes.d_mm)`、`hole_depth = 对应孔的 depth`（按最坏深径比孔选取）、`min_wall = min_wall_mm.value`。

---

## 3. 挂接点设计（3 处，全部低侵入）

### A. 上传链路（app/main.py `/api/upload-step` L1506 之后）
```
bbox = extract_bbox_from_step(...)          # 现有 L1506
+ features = extract_features(str(file_path))   # 新增，try/except 全包裹
+ bbox["features"] = features                    # 失败时为 None
```
`geometry` 是自由 dict → `create_context(geometry=bbox)` 零 schema 改动，`model_context.py` 不动。

### B. `rule_dfm` 取值链（src/runtime/part_analysis.py L89-110，改约 15 行）
三级优先：**extras 手填 > ctx.geometry.features 实测 > 缺失**
```python
feats = ((ctx.get("geometry") or {}).get("features")) or {}
wall_src = extras.get("min_wall") or (feats.get("min_wall_mm") or {}).get("value")
```
`details` 增加 `data_source` 字段（`manual / measured / missing`），报告如实标注数据来源。

### C. 存量 part 兜底（本零件 4xOdRrJv2S 属此类——上传时无 features）
- 新增 `POST /api/parts/{part_id}/features`：按需提取；文件路径解析 `data/uploads/` 下 glob `*_{ctx.file_name}`（上传文件名带 6-hex 前缀，`ctx.file_name` 是否含前缀在实现时先 `GET /api/parts/{id}` 核实）
- 提取结果写回 `ctx["geometry"]["features"]`（LRU 淘汰后可重新提取，幂等）
- `GET /api/parts/{part_id}`（L1722）经由 `public_context` 自动透出 features（geometry 整体返回，零改动）

### D. 聊天路径（L3494/L3513）自动受益
features 在 ctx 里 → `rule_dfm(trusted_ctx, {})` 无需改动即可拿到实测值。

---

## 4. 文件清单

| 操作 | 文件 | 规模 |
|---|---|---|
| 新增 | `src/runtime/feature_extractor.py` | ~300 行 |
| 新增 | `tests/test_feature_extractor.py`（用 data/uploads 真实件 + 损坏件 01340c_corrupt.step） | ~120 行 |
| 修改 | `app/main.py`（上传端点 +10 行；新端点 /features +25 行） | ~35 行 |
| 修改 | `src/runtime/part_analysis.py`（extras 取值链） | ~15 行 |
| 不动 | `step_parser.py`、`model_context.py`、`quote_adapter.py`、UI | 0 |

禁止硬编码原则：所有阈值（through 判定 0.05mm、轴线共线容差、体素分辨率、超时 5s）集中为模块级常量或读环境变量，与项目既有风格（`_WALL_LIMITS` 等）一致。

---

## 5. 验收标准（可测）

1. 对 4xOdRrJv2S 对应 STEP 跑 `extract_features`：产出完整 features JSON，`holes` 与 `min_wall_mm` 有值或显式 `unknowns`（不编造）
2. `POST /api/parts/4xOdRrJv2S_jsLlUVlwNOeYA/features` 后，DFM 端点 `missing_fields` 闭合 ≥2 项（hole_d/hole_depth），理想闭合 3 项（含 min_wall）
3. `details.data_source` 正确标注 manual/measured/missing 三态
4. 损坏/空 STEP（01340c_corrupt.step、05769b_empty.step）→ 不抛异常、features=None、上传流程不受影响
5. 现有 DFM 响应契约字段全部保留（向后兼容），pytest 全绿
6. 单次特征提取耗时 <2s（480KB 样件实测）

---

## 6. 风险与诚实边界

| 风险 | 对策 |
|---|---|
| 螺纹孔以底孔圆柱近似 | `thread_suspect` 标记 + warnings 提示按图纸确认规格 |
| B-spline 自由曲面孔漏检 | `freeform_faces` 计数 + 置信度降级为 medium |
| 壁厚为网格近似值 | method/confidence 字段如实标注 `approximate`，DFM 报告注明非精确实测 |
| 多实体 STEP（装配体） | 逐 solid 统计合并，`solid_count` 透出 |
| 复杂倒角（Chamfer 非 Torus） | 本期仅 Torus 圆角，Chamfer 列入 `unknowns` |
| part_id ↔ 文件对应关系 | 实现时先 GET /api/parts/{id} 核实 file_name 存储格式，再定 glob 策略 |

---

## 7. C2-C6 演进路径（C1 实测后与用户确认范围，不预承诺）

- C1 实测出炉 → 孔/壁/圆角真实数据摆给用户 → 特征全部合格 → 只出建议清单（自然达成）；发现可优化项 → 确认范围后做**受限微调**（非全自动）
- C4 报价参数在 C1 后即为实测定值：weight = features 体积×密度、thread_count = 实测孔组、surface_area_dm2 = 实测平面面积 → `QuoteAdapter.quote()` 真参数报价
- C6 打包复用 `create_bundle(files=[原STEP, features.json, 白盒报告], quote_data, metadata, reasoning_chain)`，零改造