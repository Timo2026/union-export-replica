---
name: cnc-grinding-knowledge-skill
description: "当用户需要选择磨削方式（平面磨、外圆磨、内圆磨、无心磨）或询问磨削参数时触发。适合CNC加工工艺规划、金属材料加工参数咨询场景。禁止在非加工场景讨论或纯理论力学分析时调用。"
---

---
## 何时触发
- **正向：**
- 磨削参数
- **禁止调用：**
- 非加工场景讨论或纯理论力学分析

## 输入规范
接受自然语言文本或JSON参数。
- **invoke**: `python_function` → `cnc-grinding-knowledge-skill.scripts.main.run`

## 输出规范
- cnc-grinding-knowledge-skill执行

## 执行流程
1. 解析用户输入，提取关键词
2. 加载知识库
3. 调用 `cnc-grinding-knowledge-skill.scripts.main.run` 执行查询
4. 返回结构化结果

## 边界约束
- 结果仅供参考，不替代专业工程师评估