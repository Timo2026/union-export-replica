---
name: step-factory
description: CAD STEP 文件生成工厂 - 基于 PythonOCC (miniconda) 和 FreeCAD 双引擎。支持：方块、圆柱、管材、锥形、齿轮、法兰、装配体等工业级
  STEP 文件生成。
capabilities:
- name: make_box
  description: 生成方块/长方体实心模型
  parameters:
  - name: w
    type: float
    required: true
    description: 宽度(mm)
  - name: h
    type: float
    required: true
    description: 高度(mm)
  - name: d
    type: float
    required: true
    description: 厚度(mm)
  output: STEP文件路径
  invoke:
    type: cli
    command: /home/Developer/miniconda3/envs/lk-skills/bin/python /home/Developer/.openclaw/skills/step-factory/scripts/step_occ.py
      --func make_box --params '{params}'
  example: '{"w":120,"h":80,"d":10}'
- name: make_punched_plate
  description: 生成矩形打孔板（法兰）- 支持多孔
  parameters:
  - name: w
    type: float
    required: true
    description: 宽度(mm)
  - name: h
    type: float
    required: true
    description: 长度(mm)
  - name: thickness
    type: float
    required: true
    description: 厚度(mm)
  - name: hole_rs
    type: list
    required: true
    description: 孔径列表(mm)
  - name: spacing
    type: list
    required: true
    description: 孔间距[x,y]
  output: STEP文件路径
  invoke:
    type: cli
    command: /home/Developer/miniconda3/envs/lk-skills/bin/python /home/Developer/.openclaw/skills/step-factory/scripts/step_occ.py
      punched_plate {w} {h} {thickness} {hole_rs} {spacing}
  example: '{"w":120,"h":80,"thickness":10,"hole_rs":[8],"spacing":[60,40]}'
invoke:
  type: python_function
  module: step-factory.scripts.main
  function: run
---
