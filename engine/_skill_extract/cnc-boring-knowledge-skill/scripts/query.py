#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cnc-boring-knowledge-skill - 知识查询SKILL
从真实知识库查询信息
"""
import json
from pathlib import Path

KB_PATH = Path.home() / ".openclaw/knowledge/force_deep_rag/learned_knowledge.json"

def query_knowledge(keyword, limit=10):
    """从知识库查询信息"""
    if not KB_PATH.exists():
        return {"error": "知识库不存在"}
    
    kb = json.load(open(KB_PATH))
    knowledge = kb.get("knowledge", [])
    
    results = []
    for k in knowledge:
        k_str = str(k).lower()
        if keyword.lower() in k_str:
            results.append(k)
            if len(results) >= limit:
                break
    
    return {"keyword": keyword, "count": len(results), "results": results}

def main():
    if len(sys.argv) > 1:
        keyword = sys.argv[1]
        result = query_knowledge(keyword)
        print(f"查询: {result['keyword']}")
        print(f"找到: {result['count']} 条相关知识")
        for r in result.get("results", [])[:3]:
            print(f"  - {r.get('零件类型', '未知')}")
    else:
        print("用法: python3 query.py <关键词>")

if __name__ == "__main__":
    import sys
    main()
