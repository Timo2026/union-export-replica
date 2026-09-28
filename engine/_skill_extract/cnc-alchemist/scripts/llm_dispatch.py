#!/usr/bin/env python3
"""
llm_dispatch.py - LLM模型调度
支持: NovaStudio / LM Studio / Ollama / fallback
禁止硬编码端口，自动检测
"""
import json
import time
from typing import Dict, Optional, List


def find_available_api() -> Optional[str]:
    """自动查找可用的本地API"""
    ports = [11434, 1234, 8080, 8000]
    for port in ports:
        try:
            import requests
            resp = requests.get(f"http://127.0.0.1:{port}/v1/models", timeout=1)
            if resp.status_code == 200:
                return f"http://127.0.0.1:{port}/v1"
        except:
            continue
    return None


class LLMDispatcher:
    """LLM调度器，自动适配可用后端"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.api_base = self._find_api()
        self.parser_model = self.config.get('parser_model', 'qwen2.5:3b')
        self.advisor_model = self.config.get('advisor_model', 'qwen2.5:3b')
        self.timeout = self.config.get('timeout', 90)

    def _find_api(self) -> str:
        """查找可用API"""
        # 优先使用配置的API
        configured = self.config.get('api_base')
        if configured:
            return configured.rstrip('/')

        # 自动检测
        found = find_available_api()
        if found:
            return found

        # 默认Ollama
        return "http://localhost:11434/v1"

    def _call(self, model: str, prompt: str, json_mode: bool = False,
              temperature: float = 0.2, max_retries: int = 2) -> str:
        """调用LLM"""
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "temperature": temperature,
            "max_tokens": 1024
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        for attempt in range(max_retries):
            try:
                import requests
                resp = requests.post(
                    f"{self.api_base}/chat/completions",
                    json=payload,
                    timeout=self.timeout
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                print(f"[LLM] {model} error: {e}, retry {attempt+1}")
                time.sleep(1)
        return "{}" if json_mode else ""

    def parse_features(self, text: str, existing_params: Optional[Dict] = None) -> Dict:
        """自然语言 → 特征JSON"""
        base_json = existing_params or {}
        prompt = f"""你是CNC非标零件特征提取专家。从描述中提取特征，输出纯JSON。
描述：{text}
输出格式：
{{
  "material": "材料如6061铝合金",
  "dimensions": {{"W": 长mm, "H": 宽mm, "D": 厚mm}},
  "tolerance": "IT10",
  "ra": 3.2,
  "surface_treatment": "阳极氧化",
  "quantity": 1,
  "features": [{{"type": "hole", "diameter": mm, "depth": mm}}]
}}
现有参数（优先使用）：{json.dumps(base_json, ensure_ascii=False)}"""
        raw = self._call(self.parser_model, prompt, json_mode=True)
        try:
            data = json.loads(raw)
            if not data.get("dimensions"):
                data["dimensions"] = {"W": 80, "H": 80, "D": 30}
            return data
        except:
            return {
                "material": "6061铝合金",
                "dimensions": {"W": 80, "H": 80, "D": 30},
                "features": [],
                "quantity": 1,
                "tolerance": "IT10",
                "ra": 3.2
            }

    def generate_process(self, feature_dict: Dict, geometry_info: Dict) -> str:
        """生成工艺建议"""
        prompt = f"""根据零件特征生成CNC工艺建议（刀具、转速、进给、装夹）：
{json.dumps(feature_dict, ensure_ascii=False)}
几何：体积={geometry_info.get('volume_mm3', 0):.0f}mm³，特征数={geometry_info.get('feature_count', 0)}
输出150字以内中文。"""
        return self._call(self.advisor_model, prompt)


if __name__ == '__main__':
    dispatcher = LLMDispatcher()
    print(f"API后端: {dispatcher.api_base}")
    print(f"解析模型: {dispatcher.parser_model}")
    result = dispatcher.parse_features("法兰盘，外径120，4个安装孔")
    print(f"解析结果: {result}")
