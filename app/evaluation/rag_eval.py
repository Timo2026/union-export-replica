"""rag_eval.py — RAGAS 风格 RAG 评测 (维度 4.3).

指标 (RAGAS 同名):
  faithfulness      答案是否被检索上下文支撑 (claim 覆盖率)
  context_precision 检索上下文中相关项占比 (排序敏感)
  context_recall    期望答案要点被上下文覆盖比例
  answer_relevancy  答案与问题的相关度

实现: 默认**确定性词法代理**(token/字符 n-gram 重叠), 可离线复现、无需 LLM;
      可选 llm_judge 回调 (传入则用 LLM 打分, 覆盖词法代理)。诚实标注 method。
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

_STOP = set("的 了 是 在 和 与 或 及 对 为 以 不 需 可 请 你 我 他 它 们 a an the of to is are be".split())


def _tokens(text: str) -> List[str]:
    if not text:
        return []
    # 中英混合: 英文按词, 中文按字
    toks = re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]", text.lower())
    return [t for t in toks if t not in _STOP]


def _overlap(a: str, b: str) -> float:
    ta, tb = set(_tokens(a)), set(_tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)          # Jaccard


def _coverage(answer: str, context: str) -> float:
    """answer 的 token 被 context 覆盖的比例 (faithfulness/recall 用)。"""
    ta = set(_tokens(answer))
    if not ta:
        return 0.0
    tc = set(_tokens(context))
    return len(ta & tc) / len(ta)


def faithfulness(answer: str, contexts: List[str], llm_judge: Optional[Callable] = None) -> Dict[str, Any]:
    ctx = " ".join(contexts or [])
    if llm_judge:
        return {"score": float(llm_judge("faithfulness", answer, contexts)), "method": "llm_judge"}
    return {"score": round(_coverage(answer, ctx), 4), "method": "lexical_proxy"}


def context_precision(query: str, contexts: List[str],
                      llm_judge: Optional[Callable] = None) -> Dict[str, Any]:
    if not contexts:
        return {"score": 0.0, "method": "lexical_proxy", "n": 0}
    if llm_judge:
        return {"score": float(llm_judge("context_precision", query, contexts)), "method": "llm_judge"}
    # 排序敏感: 相关项越靠前分越高 (降序秩权重 w_i = n-i, 首位权重最大)
    rel = [_overlap(query, c) for c in contexts]
    n = len(rel)
    weights = [n - i for i in range(n)]
    den = sum(rel) * sum(weights) / n if sum(rel) else 0     # 归一: 平均权重 × 总相关
    num = sum(r * w for r, w in zip(rel, weights))
    score = round(num / (sum(weights) * (sum(rel) / n)), 4) if sum(rel) else 0.0
    return {"score": min(score, 1.0), "method": "lexical_proxy",
            "n": n, "per_context_relevance": [round(x, 3) for x in rel]}


def context_recall(expected_answer: str, contexts: List[str],
                   llm_judge: Optional[Callable] = None) -> Dict[str, Any]:
    ctx = " ".join(contexts or [])
    if llm_judge:
        return {"score": float(llm_judge("context_recall", expected_answer, contexts)), "method": "llm_judge"}
    return {"score": round(_coverage(expected_answer, ctx), 4), "method": "lexical_proxy"}


def answer_relevancy(query: str, answer: str, llm_judge: Optional[Callable] = None) -> Dict[str, Any]:
    if llm_judge:
        return {"score": float(llm_judge("answer_relevancy", query, answer)), "method": "llm_judge"}
    return {"score": round(_overlap(query, answer), 4), "method": "lexical_proxy"}


def evaluate_case(case: Dict[str, Any], retrieved_contexts: List[str], answer: str,
                  llm_judge: Optional[Callable] = None) -> Dict[str, Any]:
    """对单条 RAG 黄金样例算全套 RAGAS 指标。"""
    return {
        "query": case.get("query"),
        "faithfulness": faithfulness(answer, retrieved_contexts, llm_judge),
        "context_precision": context_precision(case.get("query", ""), retrieved_contexts, llm_judge),
        "context_recall": context_recall(case.get("expected_answer", answer), retrieved_contexts, llm_judge),
        "answer_relevancy": answer_relevancy(case.get("query", ""), answer, llm_judge),
    }


def evaluate_set(cases: List[Dict[str, Any]], retrieve_fn: Callable[[str], List[str]],
                 answer_fn: Optional[Callable[[str, List[str]], str]] = None,
                 llm_judge: Optional[Callable] = None) -> Dict[str, Any]:
    """跑整个 RAG 评估集, 产出逐条 + 平均 RAGAS 分。"""
    per_case = []
    for c in cases:
        ctxs = retrieve_fn(c.get("query", ""))
        ans = c.get("answer") if c.get("answer") else (answer_fn(c.get("query", ""), ctxs) if answer_fn else "")
        per_case.append(evaluate_case(c, ctxs, ans, llm_judge))
    keys = ["faithfulness", "context_precision", "context_recall", "answer_relevancy"]
    avg = {k: round(sum(pc[k]["score"] for pc in per_case) / len(per_case), 4) for k in keys} if per_case else {}
    return {"n": len(per_case), "per_case": per_case, "average": avg,
            "method": (per_case[0]["faithfulness"]["method"] if per_case else "n/a")}
