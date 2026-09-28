#!/home/Developer/miniconda3/envs/lk-skills/bin/python
"""Reid决策操作系统 v1.0 — 分诊台 + 协议执行器
用法:
  ./reid_engine.py --input "用户输入"
  echo "用户输入" | ./reid_engine.py
"""

import sys
import os
import json
import traceback
from pathlib import Path

# 硬约束而非硬编码 — 从环境变量读取，否则用默认值
# 本机化（快轨）: 决策模型统一走本机 Nemotron Omni :8002 (vLLM OpenAI 兼容)
OLLAMA_BASE = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:8002/v1")
MODEL = os.environ.get("REID_MODEL", "nemotron-omni-30b-a3b")
TIMEOUT = int(os.environ.get("REID_TIMEOUT", "30"))

# 云端模式支持 — 设置 REID_PROVIDER=cloud 使用 DeepSeek V4 API
CLOUD_ENABLED = os.environ.get("REID_PROVIDER", "").lower() == "cloud"
CLOUD_API_KEY = os.environ.get("REID_CLOUD_KEY", "local-noauth")
CLOUD_MODEL = os.environ.get("REID_CLOUD_MODEL", "nemotron-omni-30b-a3b")
CLOUD_BASE = os.environ.get("REID_CLOUD_BASE", "http://127.0.0.1:8002/v1")

# 主系统API模式 — 设置 REID_PROVIDER=openclaw 使用 OpenClaw 主系统API
# 自动从 ~/.openclaw/openclaw.json 读取 local-reid provider 配置
OPENCLAW_ENABLED = os.environ.get("REID_PROVIDER", "").lower() == "openclaw"
def _load_openclaw_config():
    """从 OpenClaw 配置文件读取 API 配置"""
    # 使用绝对路径，避免sudo/subprocess环境下home目录不同
    # 原路径属于另一台机器; 本机对应位置（可用 env 覆盖）
    config_path = Path(os.environ.get("OPENCLAW_CONFIG",
                                    "/home/Developer/.openclaw/openclaw.json"))
    if not config_path.exists():
        return "http://127.0.0.1:8002/v1", "local-noauth", "nemotron-omni-30b-a3b"
    try:
        import json as _json
        with open(config_path) as f:
            cfg = _json.load(f)
        provider = cfg.get("models", {}).get("providers", {}).get("local-reid", {})
        base = provider.get("baseUrl", "http://127.0.0.1:8002/v1")
        key = provider.get("apiKey", "")
        model = provider.get("models", [{}])[0].get("id", "nemotron-omni-30b-a3b") if provider.get("models") else "nemotron-omni-30b-a3b"
        return base, key, model
    except Exception:
        return "http://127.0.0.1:8002/v1", "local-noauth", "nemotron-omni-30b-a3b"

_oc_base, _oc_key, _oc_model = _load_openclaw_config()
OPENCLAW_API_KEY = os.environ.get("REID_OPENCLAW_KEY", _oc_key)
OPENCLAW_MODEL = os.environ.get("REID_OPENCLAW_MODEL", _oc_model.replace("local-reid/", ""))
OPENCLAW_BASE = os.environ.get("REID_OPENCLAW_BASE", _oc_base)

# 脚本所在目录（动态路径，不写死）
SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = SCRIPT_DIR / "templates"

# 标记字典
FLAG_REMINDERS = {
    "emotional_risk": "当前有明显情绪化倾向。先停一下，确保决策不是情绪驱动。",
    "cynical_drift": "检测到犬儒倾向。保持清醒但不否定建设，信息差不等于全盘否定。",
    "control_urge": "检测到控制冲动。建议先理解对方的立场和需求，不要急于推动。",
    "sacrifice_signal": "检测到牺牲倾向。你的健康、家庭和长期信用比短期结果更重要。"
}


def load_template(name: str) -> str:
    """从文件加载 prompt 模板，动态路径，不硬编码"""
    path = TEMPLATES_DIR / name
    if not path.exists():
        # 降级：返回空字符串而非崩溃
        print(f"[警告] 模板文件不存在: {path}", file=sys.stderr)
        return ""
    return path.read_text(encoding="utf-8")


def call_ollama(
    system_prompt: str,
    user_input: str,
    json_mode: bool = False,
    timeout: int = None
) -> str:
    """调用 LLM 模型 — 支持 Ollama 本地 或 DeepSeek 云端"""
    import requests

    timeout = timeout or TIMEOUT

    if CLOUD_ENABLED:
        # ===== 云端模式：调用 DeepSeek V4 API =====
        payload = {
            "model": CLOUD_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt.strip()},
                {"role": "user", "content": user_input.strip()}
            ],
            "max_tokens": 2000,
            "temperature": 0.3
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
            payload["max_tokens"] = 500

        url = f"{CLOUD_BASE}/chat/completions"
        headers = {
            "Authorization": f"Bearer {CLOUD_API_KEY}",
            "Content-Type": "application/json"
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[Reid引擎错误] 云端调用失败: {e}", file=sys.stderr)
            return None

    if OPENCLAW_ENABLED:
        # ===== 主系统模式：本机 Omni API (nemotron-omni-30b-a3b) =====
        payload = {
            "model": OPENCLAW_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt.strip()},
                {"role": "user", "content": user_input.strip()}
            ],
            "max_tokens": 2000,
            "temperature": 0.3
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
            payload["max_tokens"] = 500

        url = f"{OPENCLAW_BASE}/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENCLAW_API_KEY}",
            "Content-Type": "application/json"
        }
        try:
            # 添加重试逻辑应对rate limit
            for attempt in range(3):
                resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
                if resp.status_code == 429:
                    wait = (attempt + 1) * 2
                    print(f"[Reid引擎] 触发限流，等待{wait}秒重试...", file=sys.stderr)
                    import time
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"].get("content", "")
                # mimo模型可能返回reasoning_content，优先用content
                if not content:
                    content = data["choices"][0]["message"].get("reasoning_content", "")
                return content
            print(f"[Reid引擎错误] 主系统API持续限流", file=sys.stderr)
            return None
        except Exception as e:
            print(f"[Reid引擎错误] 主系统API调用失败: {e}", file=sys.stderr)
            return None

    # ===== 本地模式：调用本机模型 (vLLM, OpenAI 兼容) =====
    # 本机 :8002 是 vLLM 的 OpenAI 兼容端点, 不是 Ollama 原生 /api/chat —
    # 用 OpenAI 格式: messages / max_tokens / choices[0].message.content。
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": user_input.strip()}
        ],
        "stream": False,
        "temperature": 0.3,
        "max_tokens": 2000,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
        payload["max_tokens"] = 500

    url = f"{OLLAMA_BASE}/chat/completions"
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"].get("content", "")
        # 推理型模型可能把正文放在 reasoning_content (mimo/omni 系)
        if not content:
            content = data["choices"][0]["message"].get("reasoning_content", "")
        return content
    except requests.exceptions.ConnectionError:
        print(f"[Reid引擎错误] 本机模型未运行 ({OLLAMA_BASE})", file=sys.stderr)
        return None
    except requests.exceptions.Timeout:
        print(f"[Reid引擎错误] 调用超时 ({timeout}s)", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[Reid引擎错误] {e}", file=sys.stderr)
        return None


FAMILY_KEYWORDS = ["垣钧", "幼儿园", "孩子", "爱人", "亲子", "二胎", "三胎", "老婆", "老公",
                  "赖床", "不想去", "打架", "哭", "课外", "老师", "健康", "生病",
                  "发烧", "不舒服", "妈妈", "爸爸", "夫妻", "家庭"]
WORK_KEYWORDS = ["择幂", "Xometry", "北京怀特瑞拉", "报价", "画图", "Sales Ops",
                "CRM", "周报", "Matt", "GM汇报", "Sales", "Ops", "客户",
                "销售", "运营", "Executive", "Summary", "SOP", "KPI",
                "会议", "纪要", "话术", "邮件", "客户",
                "WAIC", "石景山", "复赛", "AMD", "比赛", "路演", "演讲",
                "评委", "独角兽", "融资", "创业", "商业模式", "演示"]

def _keyword_detect(user_input: str) -> str:
    """关键词预检测 — 弥补1.5B分类不准"""
    text = user_input.lower()
    for kw in FAMILY_KEYWORDS:
        if kw.lower() in text:
            return "family"
    for kw in WORK_KEYWORDS:
        if kw.lower() in text:
            return "work"
    return None


def triage(user_input: str) -> dict:
    """第一层：分诊台 — 路由判断"""
    # 关键词预检测
    kw_domain = _keyword_detect(user_input)

    prompt = load_template("triage_prompt.txt")
    if not prompt:
        return _default_triage(kw_domain)

    raw = call_ollama(prompt, user_input, json_mode=True)
    result = None
    if raw:
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                try:
                    result = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

    if not result:
        result = _default_triage(kw_domain)

    # 关键词覆盖：模型可能误判，关键词更可靠
    if kw_domain:
        result["domain"] = kw_domain
        if kw_domain == "family":
            # 任何family输入，只要模型类型不是family_*，就强制覆盖
            if not result.get("type", "").startswith("family_"):
                # 根据关键词判断具体类型
                text_lower = user_input.lower()
                if any(w in text_lower for w in ["哭", "情绪", "生气", "难过", "害怕", "不想去", "打架", "冲突", "心情"]):
                    result["type"] = "family_emotional"
                    result["template"] = "情绪安全"
                elif any(w in text_lower for w in ["健康", "生病", "发烧", "医院", "体检", "咳嗽", "受伤"]):
                    result["type"] = "family_health"
                    result["template"] = "健康红线"
                elif any(w in text_lower for w in ["二胎", "三胎", "夫妻", "爱人", "老婆", "老公", "规划"]):
                    result["type"] = "family_planning"
                    result["template"] = "家庭规划"
                else:
                    result["type"] = "family_education"
                    result["template"] = "教育决策"
        elif kw_domain == "work":
            # 工作领域：加强深度研究匹配
            text_lower = user_input.lower()
            if any(w in text_lower for w in ["为什么", "分析一下", "原因", "趋势", "为什么最近", "怎么提高", "如何优化", "方法论", "SOP", "分析", "融合", "脚本", "逐字稿"]):
                if result.get("type", "") == "daily_digest":
                    result["type"] = "deep_research"
                    result["template"] = "深度研究"

    return result


def _default_triage(kw_domain: str = None) -> dict:
    """降级：默认分诊结果"""
    if kw_domain == "family":
        return {"domain": "family", "type": "family_education", "flags": {},
                "complexity": "low", "template": "教育决策"}
    return {"domain": "general", "type": "quick_qa", "flags": {},
            "complexity": "low", "template": "快速问答"}


def build_intervention_block(flags: dict) -> str:
    """构建拉闸干预区块"""
    triggered = [k for k, v in flags.items() if v]
    if not triggered:
        return ""

    reminders = [FLAG_REMINDERS.get(k, "") for k in triggered]
    reminder_text = "\n".join(f"- {r}" for r in reminders if r)

    block = load_template("intervention.txt")
    if block:
        return block.format(flags="、".join(triggered), reminder=reminder_text)
    
    # 降级：硬约束已有 reminder_text
    return f"## 拉闸干预\n{reminder_text}\n\n---\n"


# 路由类型→模板文件映射
ROUTE_TEMPLATES = {
    # 工作领域
    "daily_digest": "daily_protocol.txt",
    "deep_research": "deep_research_protocol.txt",
    "quick_qa": "quick_qa_protocol.txt",
    "meeting_minutes": "meeting_protocol.txt",
    "report": "report_protocol.txt",
    "sandbox": "sandbox_protocol.txt",
    "brainstorm": "brainstorm_protocol.txt",
    # 家庭领域
    "family_education": "family_education_protocol.txt",
    "family_emotional": "family_emotional_protocol.txt",
    "family_planning": "family_planning_protocol.txt",
    "family_health": "family_health_protocol.txt",
}


def select_template(triage_result: dict) -> str:
    """第二层：根据路由结果选择对应协议模板"""
    domain = triage_result.get("domain", "general")
    rtype = triage_result.get("type", "")

    # 家庭领域：匹配 family_* 类型
    if domain == "family":
        template_file = ROUTE_TEMPLATES.get(rtype)
        if template_file:
            return template_file
        # fallback: 用通用家庭模板
        return "family_protocol.txt"

    # 工作领域：精确匹配路由类型
    template_file = ROUTE_TEMPLATES.get(rtype)
    if template_file:
        return template_file

    # 未知类型 → 通用工作模板
    return "work_protocol.txt"


def execute_protocol(user_input: str, triage_result: dict) -> str:
    """第三层：协议执行 — 按模板生成结构化输出"""
    template_name = select_template(triage_result)
    template = load_template(template_name)
    if not template:
        return "[Reid引擎错误] 协议模板加载失败"

    # 填充模板变量
    routing_type = triage_result.get("template", "快速问答")
    system_prompt = template.replace("{routing_type}", routing_type)

    result = call_ollama(system_prompt, user_input)
    if result is None:
        return "[Reid引擎错误] 协议执行失败，Ollama不可用"
    return result


def main():
    # 读取输入：优先 --input 参数，其次 stdin
    user_input = ""
    if len(sys.argv) > 2 and sys.argv[1] == "--input":
        user_input = sys.argv[2]
    elif not sys.stdin.isatty():
        user_input = sys.stdin.read().strip()
    elif len(sys.argv) > 1:
        user_input = sys.argv[1]

    if not user_input:
        print("用法: reid_engine.py --input <用户输入>")
        print("  或: echo '<用户输入>' | reid_engine.py")
        sys.exit(1)

    # 元信息头
    provider = "Local-Omni" if OPENCLAW_ENABLED else ("Local-Omni" if CLOUD_ENABLED else f"Ollama({MODEL})")
    print(f"⚙️ Reid OS v1.0 | 模型: {provider}")
    print(f"---\n")

    # ===== 第一步：分诊 =====
    print(f"[1/2] 分诊中...")
    triage_result = triage(user_input)
    domain = triage_result.get("domain", "?")
    rtype = triage_result.get("type", "?")
    flags = triage_result.get("flags", {})
    print(f"  领域: {domain} | 类型: {rtype}")
    triggered = [k for k, v in flags.items() if v]
    if triggered:
        print(f"  信号: ⚠️ {'、'.join(triggered)}")
    print()

    # ===== 拉闸检查（可选） =====
    intervention_block = ""
    if any(v for v in flags.values()):
        intervention_block = build_intervention_block(flags)
        print("[拉闸干预已触发]")

    # ===== 第二步：协议执行 =====
    print(f"[2/2] 协议执行中...")
    analysis = execute_protocol(user_input, triage_result)

    # ===== 组合输出 =====
    full_output = intervention_block
    if intervention_block:
        full_output += "\n"
    full_output += analysis

    print("\n" + "=" * 40)
    print(full_output)

    # ===== 资产追问嵌入（仅工作领域且未触发拉闸且输出中无资产追问时补充） =====
    has_asset_q = "资产" in full_output or "沉淀" in full_output
    if domain == "work" and not triggered and not has_asset_q:
        print("\n---\n💡 资产追问：这件事能否沉淀为方法/模板/案例？")

    # ===== 资产沉淀记录 =====
    if domain in ("work", "family"):
        _log_asset(user_input, full_output, triage_result)

    # ===== quote-ptuning 报价集成 =====
    quote_result = _try_quote_integration(user_input)
    if quote_result:
        print("\n" + "=" * 40)
        print(quote_result)


QUOTE_SCRIPT = SCRIPT_DIR.parent.parent / "reference-quote" / "scripts" / "reference_quote.py"


def _try_quote_integration(user_input: str) -> str:
    """检测报价意图，自动调用 quote-ptuning 生成报价"""
    import subprocess
    import re

    text = user_input.lower()
    # 报价触发词 — 覆盖各种自然语言表达
    # 报价触发词：含"价"捕获报价/价格/单价/报个价等所有变体
    if not any(w in text for w in ["价", "成本", "利润", "零件", "加工", "CNC"]):
        return ""

    if not QUOTE_SCRIPT.exists():
        return ""

    # 尝试从输入中提取报价参数
    # 格式1: "法兰盘 10件 6061 阳极氧化"
    # 格式2: 自然语言包含零件名、数量等
    part = "零件"
    qty = "10"
    material = "6061铝合金"
    surface = "阳极氧化黑色"

    # 提取零件名
    m = re.search(r'(.{2,6})(?:\s+)(\d+)(?:件|个|只)', user_input)
    if m:
        part = m.group(1).strip()
        qty = m.group(2)

    try:
        result = subprocess.run(
            [str(QUOTE_SCRIPT), part, qty, material, surface],
            capture_output=True, text=True, timeout=15,
            cwd=str(QUOTE_SCRIPT.parent)
        )
        if result.returncode == 0:
            lines = [l for l in result.stdout.split("\n") if l.strip()]
            quote_lines = [l for l in lines if "报价" in l or "单价" in l or "总价" in l or "小计" in l or "利润" in l]
            if quote_lines:
                return "\n".join(["📊 自动报价", "---"] + quote_lines)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return ""


def _log_asset(user_input: str, output: str, triage_result: dict):
    """将含资产追问的输出追加写入资产日志"""
    from datetime import date
    import os

    assets_dir = SCRIPT_DIR.parent / "assets"
    os.makedirs(assets_dir, exist_ok=True)

    log_path = assets_dir / "assets_log.md"
    today = date.today().isoformat()
    domain = triage_result.get("domain", "?")
    rtype = triage_result.get("type", "?")

    # 摘取资产相关内容（输出末尾部分）
    lines = output.strip().split("\n")
    asset_lines = [l for l in lines if "资产" in l or "沉淀" in l or "方法" in l]
    asset_summary = "\n".join(asset_lines[-3:]) if asset_lines else "(参见完整输出)"

    entry = (
        f"\n### {today} | {domain}/{rtype}\n"
        f"- **输入**: {user_input[:80]}...\n"
        f"- **资产摘要**: {asset_summary}\n"
        f"- **完整输出**: `reid-operating-system`\n"
    )

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)


if __name__ == "__main__":
    main()
