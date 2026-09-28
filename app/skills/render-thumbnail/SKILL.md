---
name: render-thumbnail
description: 用真实 OCP B-rep 生成 STEP 等角投影 SVG 缩略图与几何摘要（体积/质量/特征数）。
version: 1
iron_rule: deterministic
backend: services/step_thumbnail.py:make_thumbnail
openshell_policy: [local-only, skill-allowlist]
tool_contract:
  openai_function:
    name: render_thumbnail
    description: STEP SVG 缩略图
    parameters:
      type: object
      properties:
        path: {type: string}
      required: [path]
---
# render-thumbnail

路径必须在 data/ 等沙箱白名单内（OpenShell local-only）。
