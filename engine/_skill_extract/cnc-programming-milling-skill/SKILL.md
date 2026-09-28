---
name: cnc-programming-milling-skill
description: "当用户需要编写或调试CNC铣削程序，特别是涉及G代码（如G00/G01直线插补、G02/G03圆弧）、M代码（如M03主轴正转、M08切削液开）、固定循环（如G81钻孔、G84攻丝）或子程序调用时触发。适合制造工程师、数控程序员在CAM后处理或手动编程阶段使用。禁止在数控车削、3D打印、激光切割等非铣削场景下调用。"
---

---
## 何时触发
- **正向：**
- cnc programming milling skill
- **禁止调用：**
- 数控车削、3D打印、激光切割等非铣削场景下

## 输入规范
接受自然语言文本或JSON参数。
- **invoke**: `python_function` → `cnc-programming-milling-skill.scripts.main.run`

## 输出规范
- 执行CNC铣削编程技能的主功能

## 执行流程
1. 解析用户输入，提取关键词
2. 加载知识库
3. 调用 `cnc-programming-milling-skill.scripts.main.run` 执行查询
4. 返回结构化结果

## 边界约束
- 固定循环中的安全平面(R平面)高度必须设置在工件最高点以上，否则刀具快速移动时极易撞刀。
- 使用子程序(M98)时，注意主程序中的模态指令（如G90绝对坐标、G91增量坐标）会影响子程序内的运动模式，需在子程序开头明确指定。