---
name: electroplating-knowledge
description: "SKILL.md - 电镀表面处理知识"
---

name: electroplating-knowledge
description: 电镀表面处理知识
category: auto_generated
version: 1.0

## 基本信息
description: electroplating-knowledge 知识查询
# SKILL.md - 电镀表面处理知识

## 基本信息
- **技能名称**: 电镀表面处理知识
- **分类**: 电镀工艺
- **触发关键词**: 电镀 electroplating zinc nickel
- **知识来源**: 从12934条学习知识中提取
- **匹配条目**: 约130条相关知识
- **示例文件**: 知识库条目

## 技能描述
本技能封装了电镀工艺相关的制造知识，包括材料选用、加工工艺、质量要点、国标参考等。基于约130条真实学习知识生成。

## 触发条件
当用户询问以下内容时触发本技能：
- 电镀相关零件的报价
- 电镀的加工工艺选择
- 电镀的材料选用建议
- 电镀的质量标准参考

## 使用方法
1. 识别零件类型为电镀工艺
2. 查询知识库中的电镀工艺知识
3. 根据材料、工艺、质量要求进行报价分析
4. 引用相关国标和质量标准

## 关联技能
- cad-step-rag (STEP文件解析)
- metal-kbs (金属材料知识图谱)
- quote-ptuning (精准报价技能)
- surface-treatment-knowledge (表面处理知识)

## 知识库来源
从 `~/.openclaw/knowledge/force_deep_rag/learned_knowledge.json` 中提取，
通过关键词 "电镀" 匹配约130条记录。

---
*由深度知识提炼系统自动生成 | 电镀工艺 | 禁止硬编码*

---
## 何时触发
- **正向：**
- electroplating knowledge
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
