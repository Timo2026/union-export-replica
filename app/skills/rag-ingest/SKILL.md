---
name: rag-ingest
description: 把文件（PDF/邮件/图纸说明/ZIP 嵌套包）灌入分层 RAG 的 L4 文档层，并可重建 L2 历史报价向量索引。当需要为新客户资料、PO 文档、工艺说明做可检索入库时调用。数据只落本地 (data-stays-local)。
version: 1
iron_rule: deterministic
backend: scripts 复用 services.rag_layers:LayeredRAGGateway.ingest_file/index_all_quotes
tool_contract:
  openai_function:
    name: rag_ingest
    description: 文件入库 + 报价索引重建 (本地向量库)
    parameters:
      type: object
      properties:
        action: {type: string, enum: [ingest_file, reindex_quotes, list_docs]}
        file_path: {type: string, description: 本地绝对/相对路径 (工具内强制转绝对)}
        customer_id: {type: string}
      required: [action]
---

# rag-ingest

## 何时用
拿到新文档（客户图纸说明、PO、工艺卡）需要进 RAG 供黄金链检索时。**不新建向量库轮子** —
全部委托 `services.rag_layers.LayeredRAGGateway`（:1278 在线 embed，不可达显式 HashEmbedder 降级）。

## 输入 / 输出
- `ingest_file`: `{file_path, customer_id?}` → gateway.ingest_file（ZIP 自动展开嵌套）
- `reindex_quotes`: 无参 → gateway.index_all_quotes()，返回重建条数
- `list_docs`: `{customer_id?}` → 已入库文档清单

## 契约与失败策略
- file_path 一律 `Path.resolve()` 为绝对路径（内核桥 cwd 铁律）。
- 文件不存在 → `{ok: false}` 显式报错，不静默跳过。
- 客户数据只写本地 data/ (gitignored)，绝不出网。

## 示例
`run(action="ingest_file", file_path="C:/.../PO-C1001-tech.pdf", customer_id="JIEVO")`
→ `{ok: true, doc_id: "PO-C1001-tech"}`
