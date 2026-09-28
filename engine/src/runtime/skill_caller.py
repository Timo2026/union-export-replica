# -*- coding: utf-8 -*-
class SkillCaller:
    def __init__(self):
        self._skills = {}
    def register(self, name, func, meta=None):
        self._skills[name] = {"func": func, "meta": meta or {}}
    def list_available(self):
        return list(self._skills.keys())
    def call(self, name, **kwargs):
        s = self._skills.get(name)
        if not s:
            return {"error": "skill not found: " + name}
        return s["func"](**kwargs)
