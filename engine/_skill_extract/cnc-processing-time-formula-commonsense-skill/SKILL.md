---
name: cnc-processing-time-formula-commonsense-skill
description: "当用户提到CNC加工时间估算、公式计算或询问“大概要多久”时触发。适合对CNC零件加工时间进行快速、经验性估算的场景。禁止在需要精确定价、正式报价或编程级精确时间计算时调用。"
---

---
## 何时触发
- **正向：**
- 加工时间估算
- CNC公式
- 大概要多久
- **禁止调用：**
- 需要精确定价、正式报价或编程级精确

## 输入规范
接受自然语言文本或JSON参数。
- **invoke**: `python_function` → `cnc-processing-time-formula-commonsense-skill.scripts.main.run`

## 输出规范
- 执行CNC加工时间经验估算与常识性计算。

## 执行流程
1. 解析用户输入，提取关键词
2. 加载知识库
3. 调用 `cnc-processing-time-formula-commonsense-skill.scripts.main.run` 执行查询
4. 返回结构化结果

## 边界约束
- 结果仅供参考，不替代专业工程师评估