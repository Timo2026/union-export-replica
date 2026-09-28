---
name: cnc-quality-control-skill
description: "name: cnc-quality-control-skill"
---

name: cnc-quality-control-skill
category: auto_generated
version: 1.0
description: 当用户提及CNC加工、首件/末件检验或生产过程质量控制时触发。适用于生产准备、过程监控及交付前质检环节。禁止在非生产环境或设备未校准状态下调用。
capabilities:
- name: execute
  description: 执行CNC质量控制流程，覆盖首件检验、过程检验与末件检验
易错点:
1. 首件检验时忽略机床热机状态（冷态与热态精度差异可达0.005mm）
2. 过程检验中仅测量尺寸却忽略刀具磨损导致的表面粗糙度突变
3. 三坐标测量室温波动±2℃即可引发工件微变形（需恒温20±1℃）
---
## 何时触发
- **正向：**
- cnc quality control skill
- **禁止调用：**
- 非生产环境或设备未校准状态下

## 输入规范
接受自然语言文本查询。

## 输出规范
- 执行CNC质量控制流程，覆盖首件检验、过程检验与末件检验

## 执行流程
1. 解析用户输入，提取关键词
2. 从知识库中匹配相关条目
3. 整理并返回结构化结果

## 边界约束
- 结果仅供参考，不替代专业工程师评估
