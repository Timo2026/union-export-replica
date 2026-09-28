---
name: cnc-boring-knowledge-skill
description: "当用户需要镗削加工方案、提到粗镗精镗浮动镗珩磨选用、询问镗削参数设置时触发。适合CNC编程、工艺制定、刀具选用场景。禁止在车削铣削钻孔等非镗削加工场景调用。"
---

---
## 何时触发
- **正向：**
- 粗镗精镗浮动镗珩磨选用、询问镗削参数设置
- **禁止调用：**
- 车削铣削钻孔等非镗削加工场景

## 输入规范
接受自然语言文本或JSON参数。
- **invoke**: `python_function` → `cnc-boring-knowledge-skill.scripts.main.run`

## 输出规范
- cnc-boring-knowledge-skill执行

## 执行流程
1. 解析用户输入，提取关键词
2. 加载知识库
3. 调用 `cnc-boring-knowledge-skill.scripts.main.run` 执行查询
4. 返回结构化结果

## 边界约束
- 结果仅供参考，不替代专业工程师评估