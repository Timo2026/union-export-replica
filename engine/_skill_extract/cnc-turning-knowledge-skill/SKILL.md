---
name: cnc-turning-knowledge-skill
description: "name: cnc-turning-knowledge-skill"
---

name: cnc-turning-knowledge-skill
category: auto_generated
version: 1.0
description: 当用户正在讨论CNC车削加工工艺、提到刀具选型或切削参数时触发。适合制定加工方案、优化切削参数、诊断加工问题（如振刀、表面粗糙）的场景。禁止在需要直接控制机床（PLC指令）、查询实时设备状态或处理非车削类工艺（如铣削、磨削）时调用。
metadata:
  openclaw:
    emoji: 🔩
    domain_expertise_notes: |-
      1.  车削不锈钢时，极易产生粘刀和加工硬化。经验上应选用锋利槽型并配合高压冷却，否则刀具磨损会异常加快。
      2.  切断刀的宽度选择不是随意的，需严格匹配机床切断能力及工件直径，过宽易振刀，过窄则刚性不足易折断。
      3.  内孔车刀的刀杆伸出长度有极限，经验上遵循“最小悬伸”原则，超过刀杆直径2-3倍时振动风险急剧增加。
materials:
- 铝材
- 碳钢
- 合金钢
- 不锈钢
- 铜合金
invoke:
  type: python_function
  module: cnc-turning-knowledge-skill.scripts.main
  function: run
capabilities:
- name: execute
  description: 执行CNC车削知识查询与推理。
---
## 何时触发
- **正向：**
- CNC车削加工工艺、提到刀具选型或切削参数
- **禁止调用：**
- 需要直接控制机床（PLC指令）、查询实

## 输入规范
接受自然语言文本或JSON参数。
- **invoke**: `python_function` → `cnc-turning-knowledge-skill.scripts.main.run`

## 输出规范
- 执行CNC车削知识查询与推理。

## 执行流程
1. 解析用户输入，提取关键词
2. 加载知识库
3. 调用 `cnc-turning-knowledge-skill.scripts.main.run` 执行查询
4. 返回结构化结果

## 边界约束
- 结果仅供参考，不替代专业工程师评估
