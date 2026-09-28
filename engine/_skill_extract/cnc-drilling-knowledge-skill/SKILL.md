---
name: cnc-drilling-knowledge-skill
description: "name: cnc-drilling-knowledge-skill"
---



```markdown
name: cnc-drilling-knowledge-skill
category: auto_generated
version: 1.0
description: 当用户需要选用钻头类型（麻花钻、中心钻、锪钻、镗钻）、了解钻孔参数设置、或提到镗孔/锪孔/铰孔等加工工艺时触发。适合CNC加工编程、零件工艺制定、钻头选用咨询等场景。禁止在用户询问车削、铣削、磨削等其他加工方法时调用。
metadata:
  openclaw:
    emoji: ⚙️
processes:
- 钻孔
- 锪孔
- 镗孔
- 铰孔
invoke:
  type: python_function
  module: cnc-drilling-knowledge-skill.scripts.main
  function: run
capabilities:
- name: execute
  description: cnc-drilling-knowledge-skill执行
  parameters: []
common_pitfalls:
  - **错误现象**：混淆锪钻和镗钻的用途，建议用镗孔方式加工孔口平面
    **根因**：未区分锪孔（加工孔口沉头孔、倒角、平整端面）与镗孔（扩大孔径、修正孔轴线）的本质区别
    **正确做法**：孔口加工应选用锪钻或端面铣刀；扩大孔径或修正偏心才用镗刀
    **触发场景**：用户询问如何加工孔口沉头孔、如何在孔上方打平底时
  - **错误现象**：不
---
## 何时触发
- **正向：**
- 镗孔/锪孔/铰孔等加工工艺
- **禁止调用：**
- 用户询问车削、铣削、磨削等其他加工方法

## 输入规范
接受自然语言文本或JSON参数。
- **invoke**: `python_function` → `cnc-drilling-knowledge-skill.scripts.main.run`

## 输出规范
- cnc-drilling-knowledge-skill执行

## 执行流程
1. 解析用户输入，提取关键词
2. 加载知识库
3. 调用 `cnc-drilling-knowledge-skill.scripts.main.run` 执行查询
4. 返回结构化结果

## 边界约束
- 结果仅供参考，不替代专业工程师评估
