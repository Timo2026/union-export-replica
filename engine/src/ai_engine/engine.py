# -*- coding: utf-8 -*-
class EngineError(Exception):
    pass

class AIEngine:
    def __init__(self, config=None):
        self.config = config or {}
    def chat(self, prompt, system_prompt="", temperature=0.3, max_tokens=2048):
        raise EngineError("AIEngine base class does not implement chat()")
    def chat_json(self, prompt, system_prompt="", temperature=0.3, max_tokens=2048):
        raise EngineError("AIEngine base class does not implement chat_json()")
