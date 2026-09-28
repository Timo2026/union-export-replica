---
name: opc-dfm-router
version: 1.0
description: DFM可制造性检查路由引擎。基于dfm_checker.py + interaction_matrix.py + pipeline.py，对零件图纸执行可制造性审查，输出DFM问题清单与工艺建议。
invoke:
  type: python_function
  module: opc-dfm-router.scripts.pipeline
  function: run
---
# opc-dfm-router

DFM检查流水线：几何解析 → 交互矩阵 → 可制造性评分 → 问题清单。

## 用法
```bash
python3 scripts/pipeline.py <step_file>
```
