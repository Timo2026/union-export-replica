---
name: cnc-speed-feed-calculation-skill
description: "当用户询问切削参数计算、提到加工材料时触发。适合数控编程与加工场景。禁止在材料未明确或参数范围不合理时调用。"
---

---
## 何时触发
- **正向：**
- 切削参数计算、提到加工材料
- **禁止调用：**
- 材料未明确或参数范围不合理

## 输入规范
接受自然语言文本或JSON参数。
- **invoke**: `python_function` → `cnc-speed-feed-calculation-skill.scripts.main.run`

## 输出规范
- 计算并返回切削参数（如线速度、进给量、背吃刀量）

## 执行流程
1. 解析用户输入，提取关键词
2. 加载知识库
3. 调用 `cnc-speed-feed-calculation-skill.scripts.main.run` 执行查询
4. 返回结构化结果

## 边界约束
- 相同材料在不同加工阶段（如粗车与精车）的推荐参数差异大，直接套用常导致刀具磨损或表面质量不达标。
- 公式中的常数（如切削系数）选择易错，忽略机床刚性、刀具材质会导致计算结果超出机床承受范围。