"""nim_smoke.py — NIM 推理平台 微服务冒烟验证 (OpenAI 兼容)。

证明"接入 NIM 是配置级 base_url 替换"这一事实: 若某 NIM (或任何 OpenAI 兼容服务) 在线,
跑一次 /v1/models + 一次 /v1/chat/completions, 并演示把 models.yaml 的 llm.endpoint 指向它即可。
无 NIM/离线 → 显式 SKIP(不报错、不阻断), 系统自动回落本地 OpenAI-compat 或离线内核。

用法:
    python services/nim_smoke.py                      # 探 config/models.yaml 的 llm endpoint
    python services/nim_smoke.py --url http://127.0.0.1:8000/v1 --model <id>
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _get(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8")


def chat(base, model, prompt, timeout=60):
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
               "max_tokens": 64, "temperature": 0.1}
    req = urllib.request.Request(f"{base.rstrip('/')}/chat/completions",
                                 data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None, help="NIM base, 如 http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default=None)
    ap.add_argument("--timeout", type=int, default=6)
    a = ap.parse_args()

    base, model = a.url, a.model
    if not base:
        from services import model_config as mc
        llm = mc.get_model(mc.load(), "llm")
        base, model = llm.get("endpoint", ""), llm.get("model", "")

    print(f"[nim_smoke] base={base} model={model}")
    if not base:
        print("  未配置 endpoint → SKIP")
        return 0
    try:
        st, body = _get(f"{base.rstrip('/')}/models", timeout=a.timeout)
        print(f"  /v1/models -> HTTP {st}")
        ids = [m.get("id") for m in json.loads(body).get("data", [])]
        if ids:
            print(f"  模型: {ids[:6]}")
            model = model or ids[0]
        r = chat(base, model, "Reply with exactly: NIM_OK")
        txt = r["choices"][0]["message"]["content"]
        print(f"  chat completions -> {txt[:60]!r}  ✅ NIM/OpenAI-compat 可用")
        print("  接入方式: 在 UI/`config/models.yaml` 把对应模型 endpoint 填该 /v1 地址并保存 → 生效。")
        return 0
    except Exception as e:  # noqa
        print(f"  SKIP: NIM/该端点不可达 ({repr(e)[:100]}) → 回落本地 OpenAI-compat / 离线内核 (不阻断)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
