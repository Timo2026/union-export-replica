# -*- coding: utf-8 -*-
import time, uuid
from enum import Enum

class StepType(str, Enum):
    INPUT_PARSE = "input_parse"
    FEATURE_EXTRACT = "feature_extract"
    RULE_MATCH = "rule_match"
    CALCULATION = "calculation"
    INFERENCE = "inference"
    EXCLUSION = "exclusion"
    CONCLUSION = "conclusion"
    TOOL_CALL = "tool_call"
    WARNING = "warning"
    VETO = "veto"

_CHAINS = {}
_ORDER = []
# 内存驻留推理链上限：超过后淘汰最旧条目，防止长驻服务无限增长导致内存泄漏。
_MAX_CHAINS = 1000

class ReasoningChain:
    def __init__(self, name, desc=""):
        self.chain_id = uuid.uuid4().hex[:12]
        self.name = name
        self.task_type = name
        self.task_title = desc or name
        self.steps = []
        self.features = {}
        self.summary = ""
        self.overall_conclusion = ""
        self._t0 = time.time()
        self._step_seq = 0

    def _next(self):
        self._step_seq += 1
        return self._step_seq

    def add_step(self, step_type, name, desc="", evidence=None, confidence=0.0, source=None, formula=None):
        st = step_type.value if isinstance(step_type, StepType) else str(step_type)
        self.steps.append({
            "step_id": self._next(), "step_type": st, "title": name,
            "description": desc, "evidence": evidence, "confidence": confidence,
            "source": source, "formula": formula,
        })

    def add_input(self, k, v, source=None):
        self.add_step(StepType.INPUT_PARSE, "输入: " + str(k), str(v), evidence=v, source=source)

    def add_feature(self, k, v, desc=""):
        self.features[k] = v
        self.add_step(StepType.FEATURE_EXTRACT, "特征: " + str(k), desc or str(v), evidence=v)

    def add_inference(self, title, content, confidence=0.0, evidence=None):
        self.add_step(StepType.INFERENCE, title, content, confidence=confidence, evidence=evidence)

    def add_warning(self, msg, severity="warn"):
        self.add_step(StepType.WARNING, "警告", msg, confidence=0.5, source=severity)

    def add_conclusion(self, title, confidence=0.0, rationale="", recommendations=None):
        self.overall_conclusion = rationale or title
        self.add_step(StepType.CONCLUSION, title, rationale, confidence=confidence,
                      evidence=recommendations)

    def finalize(self, summary=""):
        self.summary = summary
        register_chain(self)
        return self

    def to_dict(self):
        total = len(self.steps)
        confs = [s.get("confidence", 0) for s in self.steps if s.get("confidence")]
        overall = (sum(confs) / len(confs)) if confs else 0.0
        return {
            "chain_id": self.chain_id,
            "task_type": self.task_type,
            "task_title": self.task_title,
            "total_steps": total,
            "elapsed_ms": (time.time() - self._t0) * 1000,
            "overall_confidence": overall,
            "overall_conclusion": self.overall_conclusion,
            "steps": self.steps,
            "summary": self.summary,
        }

def register_chain(chain):
    _CHAINS[chain.chain_id] = chain
    _ORDER.insert(0, chain.chain_id)
    # 容量淘汰：超过上限时丢弃最旧条目（_ORDER 末尾），释放内存
    while len(_ORDER) > _MAX_CHAINS:
        old_id = _ORDER.pop()
        _CHAINS.pop(old_id, None)

def get_chain(chain_id):
    return _CHAINS.get(chain_id)

def get_recent_chains(limit=10):
    out = []
    for cid in _ORDER[:limit]:
        c = _CHAINS.get(cid)
        if c:
            d = c.to_dict()
            out.append({"chain_id": d["chain_id"], "task_type": d["task_type"],
                        "task_title": d["task_title"]})
    return out
