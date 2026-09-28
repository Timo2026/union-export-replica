---
name: titanium-alloy-knowledge
description: "SKILL.md - 钛合金加工知识"
---

name: titanium-alloy-knowledge
description: 钛合金加工知识
category: auto_generated
version: 1.0

## 基本信息
description: titanium-alloy-knowledge 知识查询
# SKILL.md - 钛合金加工知识

## 基本信息
- **技能名称**: 钛合金加工知识
- **分类**: 钛合金材料
- **触发关键词**: 钛合金 titanium alloy Ti6Al4V
- **知识来源**: 从12934条学习知识中提取
- **匹配条目**: 约38条相关知识
- **示例文件**: 2_肘关节固定端固定轴筒.STEP, 45偏转外固定件.STEP, 2-CP-DM-Positioning-B.step

## 技能描述
本技能封装了钛合金材料相关的制造知识，包括材料选用、加工工艺、质量要点、国标参考等。基于约38条真实学习知识生成。

## 触发条件
当用户询问以下内容时触发本技能：
- 钛合金相关零件的报价
- 钛合金的加工工艺选择
- 钛合金的材料选用建议
- 钛合金的质量标准参考

## 使用方法
1. 识别零件类型为钛合金材料
2. 查询知识库中的钛合金材料知识
3. 根据材料、工艺、质量要求进行报价分析
4. 引用相关国标和质量标准

## 关联技能
- cad-step-rag (STEP文件解析)
- metal-kbs (金属材料知识图谱)
- quote-ptuning (精准报价技能)
- surface-treatment-knowledge (表面处理知识)

## 知识库来源
从 `~/.openclaw/knowledge/force_deep_rag/learned_knowledge.json` 中提取，
通过关键词 "钛合金" 匹配约38条记录。

---
*由深度知识提炼系统自动生成 | 钛合金材料 | 禁止硬编码*

---
## 何时触发
- **正向：**
- titanium alloy knowledge
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
