---
name: cnc-coolant-knowledge-skill
description: "SKILL.md"
---

# SKILL.md

name: cnc-coolant-knowledge-skill  
category: auto_generated
version: 1.0
description:  
- **触发条件**：当用户询问CNC机床切削液选用、配比、问题排查时触发。  
- **适用场景**：金属切削加工、设备维护、工艺优化等生产相关场景。  
- **禁止调用**：当切削液已严重污染（如变色、发臭、pH值超标）或设备处于非运行维修状态时，应优先建议现场处理而非知识查询。  

capabilities:  
- name: execute  
  description: 调用切削液知识库，提供乳化液、合成液、半合成液、纯油性的选用依据、配比建议及常见问题解决方案。  

易错点（真实经验）:  
1. **乳化液配比误区**：并非浓度越高越好，过浓会导致散热差、粘残留；过稀易滋生细菌、降低防锈性。需根据加工材料（如铝合金忌高pH）和季节（夏季需防霉）动态调整。  
2. **合成液兼容性陷阱**：部分合成液与机床密封圈、油漆不相容，会导致膨胀或腐蚀。更换前必须做相容性测试，避免直接全量替换。  
3. **纯油性使用限制**：纯油性切削液易产生油雾且难清洗，在高速加工或封闭式机床中需评估油雾收集系统和工人防护措施，否则可能违反安全规范。  

processes:  
- 车削、铣削、钻孔、磨削等金属切削加工  

invoke:  
  type: python_function  
  module: cnc-coolant-knowledge-skill.scripts.main  
  function: run  

---  
*注：本技能专注于知识查询，不涉及切削液采购或实时监测数据接入。*
---
## 何时触发
- **正向：**
- CNC机床切削液选用、配比、问题排查
- **禁止调用：**
- 非本技能领域范围的问题

## 输入规范
接受自然语言文本或JSON参数。
- **invoke**: `python_function` → `cnc-coolant-knowledge-skill.scripts.main.run`

## 输出规范
- 调用切削液知识库，提供乳化液、合成液、半合成液、纯油性的选用依据、配比建议及常见问题解决方案。

## 执行流程
1. 解析用户输入，提取关键词
2. 加载知识库
3. 调用 `cnc-coolant-knowledge-skill.scripts.main.run` 执行查询
4. 返回结构化结果

## 边界约束
- 车削、铣削、钻孔、磨削等金属切削加工
