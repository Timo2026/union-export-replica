# -*- coding: utf-8 -*-
import json, urllib.request

class OpenAIEngine:
    def __init__(self, api_key="none", api_url="", model=""):
        self.api_key = api_key
        self.api_url = (api_url or "").rstrip("/")
        self.model = model
    def _is_local(self):
        url = (self.api_url or "").lower()
        return any(h in url for h in ("127.0.0.1", "localhost", "0.0.0.0"))
    def chat(self, prompt, system_prompt="", temperature=0.3, max_tokens=2048):
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        body = json.dumps({
            "model": self.model, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens,
        }).encode("utf-8")
        req = urllib.request.Request(
            self.api_url + "/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + str(self.api_key)})
        # 本地大模型(如 qwen3.8-27B)推理慢, 给足时间; 云端保持适中
        timeout = 240 if self._is_local() else 60
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as e:
            return json.dumps({"status": "cloud_call_failed", "error": str(e)})
