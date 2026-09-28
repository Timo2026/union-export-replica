---
name: cnc-programming-turning-skill
description: "name: cnc-programming-turning-skill"
---

name: cnc-programming-turning-skill
category: auto_generated
version: 1.0
description: 当用户提到CNC车削编程、询问G71/G72/G73循环用法、或需要编写/优化车削粗加工程序时触发。适合处理阶梯轴、法兰盘等回转体零件的粗加工阶段。禁止在不确定机床控制系统（如FANUC、SIEMENS）和材料特性时盲目调用，以免参数错误导致撞刀或过切。
metadata:
  emoji: 🔄
materials:
- 铝材
- 碳钢
- 合金钢
invoke:
  module: cnc-programming-turning-skill.scripts.main
  function: run
capabilities:
- name: execute
  description: 生成或分析基于G71、G72、G73循环的车削加工程序段。
易错点：
1.  G71与G72的参数易混淆：G71 (外圆/内孔粗车循环) 的退刀量U(直径值)和Z向余量W均为半径值或直径值，取决于机床设定，但G72 (端面粗车循环) 的U、W定义与其相反，容易记反
---
## 何时触发
- **正向：**
- CNC车削编程、询问G71/G72/G73循环用法、或需要编写/优化车削粗加工程序
- **禁止调用：**
- 不确定机床控制系统（如FANUC、SIEMENS）和材料特性

## 输入规范
接受自然语言文本查询。

## 输出规范
- 生成或分析基于G71、G72、G73循环的车削加工程序段。

## 执行流程
1. 解析用户输入，提取关键词
2. 从知识库中匹配相关条目
3. 整理并返回结构化结果

## 边界约束
- 结果仅供参考，不替代专业工程师评估
