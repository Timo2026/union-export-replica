---
name: cnc-synthesis-pipeline
description: "当用户提到「CNC合成」「多步骤CNC处理」「端到端CNC工作流」时触发。适合需要协调5个独立SKILL完成复杂加工链路的场景。禁止在单步骤CNC操作或未明确工作流需求时调用"
---

---
## 何时触发
- **正向：**
- 「CNC合成」「多步骤CNC处理」「端到端CNC工作流」
- **禁止调用：**
- 单步骤CNC操作或未明确工作流需求

## 输入规范
接受自然语言文本或JSON参数。
- **invoke**: `python_function` → `cnc-synthesis-pipeline.scripts.main.run`

## 输出规范
- 协调CNC参数化建模、工艺仿真、刀具路径规划等子任务，自动传递中间结果

## 执行流程
1. 解析用户输入，提取关键词
2. 加载知识库
3. 调用 `cnc-synthesis-pipeline.scripts.main.run` 执行查询
4. 返回结构化结果

## 边界约束
- 工作流衔接断裂：子SKILL返回数据格式未标准化导致管道中断（需确保所有中间结果使用统一JSON Schema）
- 参数覆盖冲突：下游SKILL错误覆盖上游输出的关键参数（应显式声明参数优先级规则）