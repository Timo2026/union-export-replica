#!/usr/bin/env python3
"""evidence_rag.py - PDF证据溯源RAG"""
import os, json

EVIDENCE_DIRS = [
    "/media/timo/CE18065718063F49/图纸/",
    "/media/timo/CE18065718063F49/图纸包/",
    "/media/timo/软件/商务/",
]

class EvidenceRAG:
    def __init__(self):
        self.cache = {
            "铝合金6061": "GB/T 6892-2015 | GB/T 5237-2017 | 阳极氧化膜厚5-25μm",
            "304不锈钢": "GB/T 3280-2015 冷轧钢板 | GB/T 1220-2007 棒材 | 电解抛光Ra≤0.4μm",
            "45号钢": "GB/T 699-2015 结构钢 | 调质HRC28-32 | 发黑0.6-0.8μm",
            "工具钢": "GB/T 1299-2014 | Cr12MoV淬火HRC58-62 | SKD11回火HRC58-60",
        }
    
    def search_pdfs(self, query: str, max_r: int = 5) -> list:
        q = query.lower().split()
        results = []
        for base in EVIDENCE_DIRS:
            if not os.path.exists(base):
                continue
            for root, _, files in os.walk(base):
                if root.replace(base, "").count(os.sep) > 4:
                    continue
                for f in files[:50]:
                    if not f.lower().endswith('.pdf'):
                        continue
                    score = sum(1 for t in q if t in f.lower())
                    if score > 0:
                        results.append({
                            "file": f, "path": os.path.join(root, f),
                            "score": score, "size": os.path.getsize(os.path.join(root, f)) // 1024,
                        })
        results.sort(key=lambda x: -x["score"])
        return results[:max_r]
    
    def get_evidence(self, material: str) -> str:
        for k, v in self.cache.items():
            if k in material:
                return f"[标准] {v}"
        return ""

if __name__ == "__main__":
    rag = EvidenceRAG()
    for mat in ["铝合金6061", "304不锈钢", "45号钢"]:
        print(f"{mat}: {rag.get_evidence(mat)}")
    results = rag.search_pdfs("底座")
    print(f"搜索'底座'相关PDF: {len(results)}个")
    for r in results[:3]:
        print(f"  {r['file']} ({r['size']}KB)")
