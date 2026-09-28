# -*- coding: utf-8 -*-
import os, json, re, threading

_DOCS = []
_REGISTRY = []
_LOCK = threading.Lock()
_MAX_DOCS = 500       # 文档索引容量上限，防止内存泄漏
_MAX_REGISTRY = 1000  # 注册表容量上限

def _root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def _tokenize(text):
    return [t for t in re.split(r"[\s,，。.!！?？:：;；()（）\[\]\"\'<>]+", str(text).lower()) if t]

def index_document(doc_id, title, content, doc_type="text", tags=None):
    with _LOCK:
        rec = {"doc_id": doc_id, "title": title, "content": content,
               "doc_type": doc_type, "tags": tags or [], "tokens": _tokenize(title + " " + content)}
        _DOCS.append(rec)
        if len(_DOCS) > _MAX_DOCS:
            del _DOCS[0]  # 淘汰最旧条目
    return {"status": "ok", "doc_id": doc_id}

def search(q, top_k=5):
    q = _tokenize(q)
    scored = []
    with _LOCK:
        for d in _DOCS:
            # 修复缺陷：原 `t in d["tokens"]` 为精确 token 匹配，中文无空格分词导致
            # "6061" 无法匹配 "6061铝合金法兰"、"法兰" 无法匹配 "法兰零件"，RAG 对中文实质失效。
            # 改为子串匹配：query token 是 doc token 子串，或 doc token 是 query token 子串均算命中。
            s = sum(1 for t in q if any(t in dt or dt in t for dt in d["tokens"]))
            if s > 0:
                scored.append((s, d))
    scored.sort(key=lambda x: -x[0])
    out = []
    for s, d in scored[:top_k]:
        out.append({"title": d["title"], "doc_id": d["doc_id"], "score": s,
                    "method": "keyword", "doc_type": d["doc_type"],
                    "created_at": "", "content_preview": d["content"][:200],
                    "tags": d["tags"]})
    return out

def auto_index_all():
    result = {}
    root = _root()
    # index orders.db summary if readable
    try:
        import sqlite3
        db = os.path.join(root, "data", "orders.db")
        if os.path.exists(db):
            c = sqlite3.connect(db)
            rows = c.execute("SELECT customer_name, part_name, material, quantity, unit_price FROM orders LIMIT 100").fetchall()
            c.close()
            for i, r in enumerate(rows):
                content = " ".join(str(x) for x in r)
                index_document("order-%d" % i, "历史订单%d" % i, content, "order", ["订单"])
            result["orders"] = {"status": "ok", "count": len(rows)}
    except Exception as e:
        result["orders"] = {"status": "error", "error": str(e)}
    # index STEP files
    step_dir = os.path.join(root, "data", "step")
    n = 0
    if os.path.isdir(step_dir):
        for f in os.listdir(step_dir):
            if f.endswith(".stl") or f.endswith(".step"):
                index_document("step-" + f, f, "STEP/STL 文件 " + f, "step", ["step"])
                n += 1
    result["step"] = {"status": "ok", "count": n}
    return result

def get_stats():
    return {"documents": len(_DOCS), "registry_entries": len(_REGISTRY),
            "embedding_dim": "-"}

def register_item(item_type, name, path, level=0):
    with _LOCK:
        _REGISTRY.append({"item_type": item_type, "name": name, "path": path, "level": level})
        if len(_REGISTRY) > _MAX_REGISTRY:
            del _REGISTRY[0]  # 淘汰最旧条目

def browse_registry(parent_path=""):
    items = [r for r in _REGISTRY if str(r["path"]).startswith(parent_path)]
    return {"parent": parent_path, "items": items, "total": len(items)}
