#!/usr/bin/env python3
"""carbon-steel-material-knowledge - 知识查询SKILL"""
import json
from pathlib import Path
KB = Path.home() / ".openclaw/knowledge/force_deep_rag/learned_knowledge.json"

def query(kw, lim=10):
    if not KB.exists():
        return []
    kb = json.load(open(KB))
    return [k for k in kb.get("knowledge",[]) if kw.lower() in str(k).lower()][:lim]

if __name__ == "__main__":
    import sys
    kw = sys.argv[1] if len(sys.argv)>1 else ""
    r = query(kw)
    print(f"找到{len(r)}条相关知识")
