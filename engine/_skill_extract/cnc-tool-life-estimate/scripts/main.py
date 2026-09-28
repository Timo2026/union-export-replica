#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cnc-tool-life-estimate - 知识查询

ClawHub标准SKILL | 生成时间: 2026-05-01 19:21
"""
import json
import argparse
from pathlib import Path

KB_PATH = Path.home() / ".openclaw/knowledge/force_deep_rag/learned_knowledge.json"

def load_knowledge():
    """加载知识库，异常时返回空"""
    if not KB_PATH.exists():
        return {"status": "warning", "data": [], "message": "知识库不存在"}
    try:
        kb = json.load(open(KB_PATH))
        return {"status": "success", "data": kb.get("knowledge", [])}
    except Exception as e:
        return {"status": "error", "data": [], "message": str(e)}

def query(request="", **kwargs):
    """核心执行函数"""
    kb_result = load_knowledge()
    
    if kb_result["status"] != "success":
        return {
            "status": "error",
            "message": kb_result["message"],
            "skill": "cnc-tool-life-estimate",
            "fallback": True
        }
    
    knowledge = kb_result["data"]
    keyword = kwargs.get("keyword", request)
    limit = kwargs.get("limit", 10)
    
    results = [k for k in knowledge if keyword.lower() in str(k).lower()][:limit]
    
    return {
        "status": "success",
        "skill": "cnc-tool-life-estimate",
        "type": "knowledge",
        "keyword": keyword,
        "count": len(results),
        "results": results
    }

def run(request="", **kwargs):
    """主入口 - 符合invoke标准"""
    try:
        return query(request, **kwargs)
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "skill": "cnc-tool-life-estimate",
            "fallback": True
        }

def main():
    parser = argparse.ArgumentParser(description="cnc-tool-life-estimate - 知识查询")
    parser.add_argument("request", nargs="?", default="", help="请求/关键词")
    parser.add_argument("--keyword", "-k", help="查询关键词")
    parser.add_argument("--limit", "-l", type=int, default=10, help="返回数量")
    args = parser.parse_args()
    
    kw = args.keyword or args.request
    result = run(kw, limit=args.limit)
    
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1

if __name__ == "__main__":
    exit(main() or 0)
