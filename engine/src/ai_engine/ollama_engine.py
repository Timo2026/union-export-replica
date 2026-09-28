# -*- coding: utf-8 -*-
import json, os, urllib.request

# Ollama 服务地址：优先环境变量 OLLAMA_URL，兜底默认本地 11434（禁止硬编码原则）
_OLLAMA_BASE = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")

class OllamaEngine:
    def __init__(self, name="qwen2.5:1.5b"):
        self.name = name
    def chat(self, prompt, system_prompt="", temperature=0.3, max_tokens=2048):
        full = (system_prompt + "\n\n" + prompt) if system_prompt else prompt
        body = json.dumps({
            "model": self.name,
            "prompt": full,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }).encode("utf-8")
        req = urllib.request.Request(
            _OLLAMA_BASE + "/api/generate",
            data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                data = json.loads(r.read())
            return data.get("response", "")
        except Exception as e:
            return json.dumps({"status": "ollama_call_failed", "error": str(e)})
