#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
design-dfm-knowledge-skill - 知识查询SKILL
从真实知识库提炼生成
"""
import json
from pathlib import Path
from typing import List, Dict

KB_PATH = Path.home() / ".openclaw/knowledge/force_deep_rag/learned_knowledge.json"

def query_knowledge(keyword: str, limit: int = 10) -> List[Dict]:
    """查询知识库"""
    if not KB_PATH.exists():
        return []
    
    kb = json.load(open(KB_PATH))
    knowledge = kb.get("knowledge", [])
    
    results = []
    for k in knowledge:
        if keyword.lower() in str(k).lower():
            results.append(k)
            if len(results) >= limit:
                break
    
    return results

def main():
    import sys
    if len(sys.argv) > 1:
        keyword = sys.argv[1]
        results = query_knowledge(keyword)
        print(f"找到{len(results)}条相关知识:")
        for r in results:
            print(f"  - {r.get('零件类型', '未知')}")
    else:
        print("用法: python3 query.py <关键词>")

if __name__ == "__main__":
    main()
