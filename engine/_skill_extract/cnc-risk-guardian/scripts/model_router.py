#!/usr/bin/env python3
"""
model_router.py - 三级降级模型路由器
Tier 1: Ollama本地GPU推理 (qwen2.5:1.5b, ~4s)
Tier 2: DeepSeek API云端推理 (备用, ~2s)
Tier 3: Rule-based降级引擎 (无模型, 零延迟)
"""
import os, sys, json, time, urllib.request, hashlib

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

class ModelRouter:
    def __init__(self):
        self.stats = {"tier1": 0, "tier2": 0, "tier3": 0, "failures": 0}
        # DeepSeek API配置
        self.ds_api_key = None
        for env_var in ["DEEPSEEK_API_KEY", "OPENAI_API_KEY"]:
            if os.environ.get(env_var):
                self.ds_api_key = os.environ[env_var]
                break
        # 也检查配置文件
        config_paths = [
            os.path.expanduser("~/.openclaw/config.yaml"),
            os.path.expanduser("~/.openclaw/config.json"),
        ]
        for cp in config_paths:
            if os.path.exists(cp):
                try:
                    with open(cp) as f:
                        cfg = json.load(f) if cp.endswith('.json') else {}
                    for key in cfg:
                        if 'api_key' in key.lower() and 'deepseek' in key.lower():
                            self.ds_api_key = cfg[key]
                except: pass
    
    def tier1_ollama(self, prompt: str, timeout_s: int = 15) -> dict:
        """Tier 1: Ollama本地推理"""
        data = {
            "model": "qwen2.5:1.5b",
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": 400, "temperature": 0.1}
        }
        t0 = time.time()
        try:
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=json.dumps(data).encode(),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                result = json.loads(resp.read())
            elapsed = time.time() - t0
            self.stats["tier1"] += 1
            return {
                "tier": 1, "model": "qwen2.5:1.5b",
                "response": result.get("response", ""),
                "elapsed": round(elapsed, 2),
                "tokens_in": result.get("prompt_eval_count", 0),
                "tokens_out": result.get("eval_count", 0),
            }
        except Exception as e:
            return {"tier": 1, "error": str(e), "response": "", "elapsed": time.time()-t0}
    
    def tier2_deepseek(self, prompt: str, timeout_s: int = 10) -> dict:
        """Tier 2: DeepSeek API云端推理"""
        if not self.ds_api_key:
            return {"tier": 2, "error": "无API key", "response": ""}
        t0 = time.time()
        try:
            data = json.dumps({
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 400,
                "temperature": 0.1,
            }).encode()
            req = urllib.request.Request(
                "https://api.deepseek.com/v1/chat/completions",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.ds_api_key}"
                }
            )
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                result = json.loads(resp.read())
            elapsed = time.time() - t0
            self.stats["tier2"] += 1
            return {
                "tier": 2, "model": "deepseek-chat",
                "response": result.get("choices", [{}])[0].get("message", {}).get("content", ""),
                "elapsed": round(elapsed, 2),
                "tokens_in": result.get("usage", {}).get("prompt_tokens", 0),
                "tokens_out": result.get("usage", {}).get("completion_tokens", 0),
            }
        except Exception as e:
            return {"tier": 2, "error": str(e), "response": "", "elapsed": time.time()-t0}
    
    def tier3_rule(self, prompt: str) -> dict:
        """Tier 3: 纯规则降级引擎（零模型依赖）"""
        t0 = time.time()
        self.stats["tier3"] += 1
        
        # 简易规则解析
        材料映射 = {
            "6061": "铝合金6061", "7075": "铝合金7075", "铝合金": "铝合金6061",
            "304": "304不锈钢", "316": "316不锈钢", "不锈钢": "304不锈钢",
            "45": "45号钢", "碳钢": "45号钢", "钢": "45号钢",
        }
        material = "未知"
        for k, v in 材料映射.items():
            if k in prompt:
                material = v
                break
        
        # 数量提取
        import re
        nums = re.findall(r'(\d+)\s*件', prompt)
        quantity = int(nums[0]) if nums else 1
        
        # 表面处理
        surface = ""
        表面词 = {"阳极氧化": "阳极氧化", "镀锌": "镀锌", "发黑": "发黑", 
                   "电解抛光": "电解抛光", "钝化": "钝化", "硬质氧化": "硬质氧化"}
        for k, v in 表面词.items():
            if k in prompt:
                surface = v
                break
        
        elapsed = time.time() - t0
        return {
            "tier": 3, "model": "rule_engine",
            "response": json.dumps({
                "material": material, "surface_treatment": surface,
                "quantity": quantity, "dimensions_mm": "",
            }, ensure_ascii=False),
            "elapsed": round(elapsed, 3),
            "tokens_in": 0, "tokens_out": 0,
        }
    
    def route(self, prompt: str, max_retries: int = 1) -> dict:
        """自动三级降级路由"""
        errors = []
        
        # Tier 1: Ollama
        result = self.tier1_ollama(prompt)
        if result.get("response") and not result.get("error"):
            return result
        
        errors.append(f"Tier1: {result.get('error', '空响应')}")
        
        # Tier 2: DeepSeek
        result = self.tier2_deepseek(prompt)
        if result.get("response") and not result.get("error"):
            return result
        
        errors.append(f"Tier2: {result.get('error', '空响应')}")
        
        # Tier 3: 规则引擎 (永不失败)
        self.stats["failures"] += 1
        result = self.tier3_rule(prompt)
        result["note"] = "降级到规则引擎" if errors else ""
        return result
    
    def get_stats(self) -> dict:
        return self.stats | {"total": sum(self.stats.values())}


# === CLI测试 ===
if __name__ == "__main__":
    router = ModelRouter()
    
    test_prompts = [
        "6061铝合金阳极氧化100件报价",
        "304不锈钢法兰镀锌50件", 
    ]
    
    for p in test_prompts:
        print(f"\n输入: {p}")
        result = router.route(p)
        print(f"Tier: {result['tier']} ({result['model']}) | 耗时: {result['elapsed']}s")
        print(f"响应: {result['response'][:100]}")
        if result.get('note'):
            print(f"备注: {result['note']}")
    
    print(f"\n统计: {router.get_stats()}")
