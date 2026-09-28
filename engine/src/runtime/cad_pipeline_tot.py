# -*- coding: utf-8 -*-
import re
from .step_generator_dual import generate_part
from .step_generator import PART_GENERATORS
from ..neuro_core.reasoning_chain import ReasoningChain, StepType

_TYPE_MAP = {"法兰": "flange", "法兰盖": "flange", "闷盖": "flange", "圆盘": "flange",
             "轴套": "sleeve", "衬套": "sleeve", "轴": "shaft", "光轴": "shaft",
             "板": "plate", "平板": "plate", "箱体": "box", "盒子": "box", "方块": "box",
             "支架": "bracket", "支板": "bracket"}

def _regex_spec(message):
    msg = message or ""
    ml = msg.lower()
    part_type = None
    for cn, en in _TYPE_MAP.items():
        if cn in msg:
            part_type = en; break
    if not part_type:
        part_type = "flange"
    params = {}
    def i(pat):
        m = re.search(pat, msg)
        return int(m.group(1)) if m else None
    v = i(r"外径\s*(\d+)") or i(r"od\s*(\d+)")
    if v: params["od"] = v
    v = i(r"内径\s*(\d+)") or i(r"id\s*(\d+)")
    if v: params["id"] = v
    v = i(r"厚\s*(\d+)") or i(r"厚度\s*(\d+)")
    if v: params["thickness"] = v
    v = i(r"直径\s*(\d+)")
    if v: params["d"] = v
    v = i(r"长\s*(\d+)")
    if v: params["length"] = v
    v = i(r"宽\s*(\d+)")
    if v: params["w"] = v
    v = i(r"高\s*(\d+)")
    if v: params["h"] = v
    return {"part_type": part_type, "params": params}

def run_tot_competition(message, structured_spec=None):
    structured_spec = structured_spec or {}
    # pipeline 1: regex (deterministic)
    p1 = _regex_spec(message)
    # pipeline 2: provided structured spec (from LLM pre-extract or caller)
    p2 = dict(structured_spec)
    # pipeline 3: default
    p3 = {"part_type": "flange", "params": {}}
    scoreboard = [
        {"pipeline": "regex", "part_type": p1["part_type"], "score": 0.9},
        {"pipeline": "structured", "part_type": p2.get("part_type", "flange"), "score": 0.8 if p2.get("part_type") else 0.2},
        {"pipeline": "default", "part_type": p3["part_type"], "score": 0.1},
    ]
    # choose best
    winner = {"source": "regex", "confidence": 0.9}
    best = p1
    if p2.get("part_type"):
        if p2.get("params"):
            best = p2; winner = {"source": "structured", "confidence": 0.8}
    chain = ReasoningChain("cad_extract", "CAD参数提取 (TOT)")
    chain.add_input("message", message)
    chain.add_step(StepType.FEATURE_EXTRACT, "正则管道", str(p1), confidence=0.9, source="regex")
    chain.add_step(StepType.FEATURE_EXTRACT, "结构化管道", str(p2), confidence=0.8, source="structured")
    chain.add_conclusion("TOT 结果", confidence=winner["confidence"], rationale="winner=" + winner["source"])
    chain.finalize()
    return {
        "part_spec": best,
        "defaulted": [],
        "winner": winner,
        "total_candidates": len(scoreboard),
        "scoreboard": scoreboard,
        "chain_dict": chain.to_dict(),
    }
