---
name: geometric-tolerance-gdt
category: auto_generated
version: 1.0
description: 几何公差GD&T技能。基于位置度、同轴度、垂直度等几何公差知识，触发条件：用户提到几何公差、GD&T、位置度、同轴度。
---

# geometric-tolerance-gdt

## 技能说明

本技能基于从真实STEP文件学习的知识库生成，专门处理相关类型零件的CNC报价场景。

## 使用方法

当用户触发本技能相关话题时，使用本技能进行报价分析和报价。

## 知识来源

知识来源：~/.openclaw/knowledge/force_deep_rag/learned_knowledge.json
生成时间：2026-04-28
学习样本：12934个真实STEP文件

---
## 何时触发
- **正向：**
- geometric tolerance gdt
- **禁止调用：**
- 非本技能领域范围的问题

## 输入规范
接受自然语言文本查询。

## 输出规范
- 返回该领域的知识查询结果和分析报告

## 执行流程
1. 解析用户输入，提取关键词
2. 从知识库中匹配相关条目
3. 整理并返回结构化结果

## 边界约束
- 结果仅供参考，不替代专业工程师评估
