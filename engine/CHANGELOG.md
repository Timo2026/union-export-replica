# Changelog — Union·由你 CNC AI 工艺大脑

所有显著变更记录于此。格式遵循 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循 [Semantic Versioning](https://semver.org/)。

## [12.0.0-fusion] — 2026-09-06 — 工业融合版

### Fixed — Bug 修复（10 项）

| # | Bug | 修复 | 文件 |
|---|-----|------|------|
| 1 | `requirements.txt` GBK 编码错误 | `PYTHONUTF8=1` 安装 | 环境变量 |
| 2 | `/api/cnc-quick` 数量解析缺失（"20个"→10） | 新增 `extract_quantity_from_message` + `QTY_PATTERN` 正则 | `app/cnc_quick.py` |
| 3 | `/api/history` 路由缺失 | 补全 GET 路由，暴露 HistoryLookup | `app/main.py` |
| 4 | README `rag/search` 方法错误 | GET → POST | `README.md` |
| 5 | README `docs` 路径错误 | `/api/docs` → `/docs` | `README.md` |
| 6 | `step_parser` error 键判断逻辑 | `"error" in bbox` → `bbox.get("error")` | `app/main.py` |
| 7 | `/api/upload` UploadFile 指针耗尽 | 调用前 `await file.seek(0)` | `app/main.py` |
| 8 | `/api/models` KeyError('source') | `m["source"]` → `m.get("source","unknown")` | `app/main.py` |
| 9 | STEP 尺寸米制未转毫米（1.13mm→1130mm） | `fix_step_unit_scale` cadquery 权威校验 | `src/runtime/step_parser.py` + `app/main.py` |
| 10 | 报价费用明细全 ¥0.00 | 补全 `material_cost/machining_cost/surface_cost` 顶层字段 | `src/runtime/quote_adapter.py` |
| 11 | 交期显示 "- 天" | 补 `lead_time_days` 别名 | `src/runtime/quote_adapter.py` |
| 12 | 重量用包围盒体积虚高（217kg→38.6kg） | cadquery `val().Volume()` 真实体积 fallback | `app/main.py` |

### Added — 新增

- `fix_step_unit_scale()` — cadquery.importStep 权威单位校验函数
- `extract_quantity_from_message()` — 自然语言数量解析（个/件/支/根/台/套/片/块/只/pcs/pieces/units/sets）
- `/api/history` GET 路由（material/customer_name/part_name/limit 查询参数）
- 报价费用三栏分解（材料费/加工费/表面处理费）
- conda `step-render` 环境支持（OCP 7.7.2.1 + cadquery 2.4.0 + cascadion 0.1.1）

### Changed — 变更

- 运行环境从 `.venv` 切换到 conda `step-render`（支持 STEP 精确几何解析）
- `cascadio` 0.1.1 作为 STEP→STL 转换的 OCC 适配器

---

## [11.x] — 历史版本

见 git log。