---
name: copper-alloy-material-knowledge
description: "SKILL.md - 铜合金材料知识库"
---

name: copper-alloy-material-knowledge
description: 铜合金材料知识库
category: auto_generated
version: 1.0

## 基本信息
description: copper-alloy-material-knowledge 知识查询


# SKILL.md - 铜合金材料知识库

## 基本信息
- **技能名称**: 铜合金材料知识库
- **分类**: 铜合金材料
- **触发关键词**: 铜合金 copper brass bronze 黄铜 青铜 白铜 紫铜
- **知识来源**: 从12934条学习知识中提取
- **匹配条目**: 约499条相关知识
- **示例文件**: JK24YCL-B06-01-020117A(1).STEP, OEM-TX315-A.00.00.01 中间块3轮(2).STEP, 202520926_MA10MCS030680.step

## 技能描述
当用户需要铜合金零件报价、材料选用建议、加工工艺选择或质量标准参考时，提到铜合金、copper、brass、bronze等关键词触发。适合铜合金材料报价分析、零件选材、加工工艺确认、质量检验等场景。禁止在用户询问非铜合金材料（铝合金、钢件、塑料件）、仅需STEP文件解析且无材料需求、或询问铜合金价格但未提供任何零件信息时调用。

## 触发条件
当用户询问以下内容时触发本技能：
- 铜合金相关零件的报价
- 铜合金的加工工艺选择
- 铜合金的材料选用建议
- 铜合金的质量标准参考

## 使用
---
## 何时触发
- **正向：**
- copper alloy material knowledge
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
