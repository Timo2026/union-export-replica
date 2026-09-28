# -*- coding: utf-8 -*-
import os, re
import yaml

def _read(p):
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        return f.read()

def _safe_yaml_load(text):
    """安全解析 YAML：失败或非 dict 时返回空字典，绝不抛异常。"""
    try:
        data = yaml.safe_load(text)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}

def _parse_expert_yaml(text):
    """解析 config/experts/*.yaml，完整保留 name/权限/提示词/schema 字段。"""
    data = _safe_yaml_load(text)
    d = {}
    for key in ("name", "has_veto", "has_override", "system_prompt", "schema"):
        if key in data:
            d[key] = data[key]
    return d

def _parse_skill_yaml(text):
    """解析 config/skills/*.yaml，完整保留 name/category/executor/description/timeout/schema。"""
    data = _safe_yaml_load(text)
    d = {}
    for key in ("name", "category", "executor", "description", "timeout", "schema"):
        if key in data:
            d[key] = data[key]
    return d

class SkillAutoLoader:
    def __init__(self, env):
        self.env = env
        self.root = None
        # project root inferred from env is not stored; use module path fallback
    def load_all(self):
        experts = {}
        skills = {}
        root = _infer_root()
        exp_dir = root / "config" / "experts"
        sk_dir = root / "config" / "skills"
        if exp_dir.exists():
            for f in exp_dir.glob("*.yaml"):
                try:
                    e = _parse_expert_yaml(_read(f))
                    if e.get("name"):
                        experts[e["name"]] = e
                except Exception:
                    continue
        if sk_dir.exists():
            for f in sk_dir.glob("*.yaml"):
                try:
                    s = _parse_skill_yaml(_read(f))
                    if s.get("name"):
                        skills[s["name"]] = s
                except Exception:
                    continue
        return {"experts": experts, "skills": skills}

def _infer_root():
    import pathlib
    return pathlib.Path(__file__).resolve().parent.parent.parent
