#!/home/Developer/miniconda3/envs/lk-skills/bin/python
"""
UnionSkill Quote Engine — API驱动的CNC报价工具

设计理念：
  - 本工具不包含任何报价逻辑，所有计算由OPC API完成
  - 本工具不包含任何AI模型，所有智能由本机 Nemotron 模型完成
  - 本工具只负责：输入解析 → API调用 → 报价单生成 → 可选3D模型

依赖：
  - OPC API (http://127.0.0.1:8002/v1 或 http://127.0.0.1:7862/api)
  - pythonOCC (可选，用于STEP 3D模型生成)
"""

import json
import sys
import os
import time
import argparse
import urllib.request
import urllib.error
from datetime import datetime

# ═══════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════
# ── 本机自有端点（铁律① data-stays-local; 严禁外发）──
# api_base   : 本机 CNC 决策内核 :7862 — 报价/DFM 确定性数字
# llm_base   : 本机 Nemotron Omni :8002 — 语言理解/草稿（本地模型）
# embed_base : 本机 Nemotron Embed-1B :8011
DEFAULT_CONFIG = {
    "api_base": "http://127.0.0.1:7862/api",
    "llm_base": "http://127.0.0.1:8002/v1",
    "embed_base": "http://127.0.0.1:8011/v1",
    "api_key": "local-noauth",
    "model": "nemotron-omni-30b-a3b",
    "timeout": 180,
}

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json")

def load_config():
    """加载配置，环境变量优先"""
    cfg = dict(DEFAULT_CONFIG)
    # 从config.json加载
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg.update(json.load(f))
    # 环境变量覆盖
    cfg["api_base"] = os.environ.get("OPC_API_BASE", cfg["api_base"])
    cfg["api_key"] = os.environ.get("OPC_API_KEY", cfg["api_key"])
    cfg["model"] = os.environ.get("OPC_MODEL", cfg["model"])
    return cfg


# ═══════════════════════════════════════════════════
# API 客户端
# ═══════════════════════════════════════════════════
class OPCClient:
    """OPC API 客户端 — 唯一的数据来源"""
    
    def __init__(self, config=None):
        self.cfg = config or load_config()
        self.base = self.cfg["api_base"].rstrip("/")
        self.llm_base = self.cfg.get("llm_base", "http://127.0.0.1:8002/v1").rstrip("/")
        # 无 _active_base 游标: 分派按路径静态决定, 不留跨服务状态。
        # 修过的 Bug: 原 _active_base 会被 LLM 成功响应覆写成 :8002, 之后制造类
        # 请求被发到 LLM 端口得 404, 且 404 走 HTTPError 分支直接 return, 不再
        # failover → 端口串扰。
        self.key = self.cfg["api_key"] or "local-noauth"
        self.model = self.cfg["model"]
        self.timeout = self.cfg.get("timeout", 30)
    
    def _request(self, path, body=None, method="GET"):
        """按路径静态分派到本机端点（无外部兜底）:
            语言类 /chat/completions /models → 本机 LLM :8002/v1
            制造类 其余                        → CNC 内核 :7862/api
        """
        is_llm = path in ("/chat/completions", "/models")
        pool = [self.llm_base] if is_llm else [self.base]
        last_err: Exception | None = None
        for base in pool:
            if not base:
                continue
            url = f"{base}{path}"
            try:
                req = urllib.request.Request(url, method=method)
                req.add_header("Content-Type", "application/json")
                req.add_header("Authorization", f"Bearer {self.key}")
                if body:
                    req.data = json.dumps(body).encode()
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                # HTTP 业务错误（含 404/405）: 该端点就是不存在或方法不对,
                # 如实返回状态码。不回退到别的端口 — 那不是兜底, 是伪装成功。
                try:
                    err_body = json.loads(e.read().decode())
                    return {"error": err_body, "http_status": e.code}
                except Exception:
                    return {"error": str(e), "http_status": e.code}
            except Exception as e:
                # 连接层失败: 记录后试下一个候选端点
                last_err = e
                continue
        return {"error": f"本机端点不可达: {last_err}" if last_err else "无可用端点",
                "tried": pool}
    
    def quote(self, material, length, width, height, quantity=1, 
              surface="无", tolerance="IT8", **extra):
        """报价"""
        body = {
            "material": material,
            "length": length,
            "width": width,
            "height": height,
            "quantity": quantity,
            "surface": surface,
            "tolerance": tolerance,
        }
        body.update(extra)
        return self._request("/quote", body, "POST")
    
    def chat(self, messages, tools=None):
        """对话（工艺对齐、材料推荐等）"""
        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 2000,
        }
        if tools:
            body["tools"] = tools
        return self._request("/chat/completions", body, "POST")
    
    def dfm(self, material, dimensions, features=None):
        """DFM检查（本机 CNC 内核 7862）。

        契约（引擎 app/main.py:864 实测）: dimensions 必须是 dict
        {"L":.., "W":.., "H":..}。传 list 会让引擎对 list 调 .items()
        → AttributeError → HTTP 500。此处统一规格化, 调用方可传 list/dict。
        """
        dims = dimensions
        if isinstance(dims, (list, tuple)):
            d = [x for x in list(dims)] + [0, 0, 0]
            dims = {"L": float(d[0]), "W": float(d[1]), "H": float(d[2])}
        elif not isinstance(dims, dict):
            dims = {}
        body = {
            "material": material,
            "dimensions": dims,
        }
        # 引擎另读 min_wall / hole_d / hole_depth（非 features 列表）
        if isinstance(features, dict):
            for k in ("min_wall", "hole_d", "hole_diameter", "hole_depth",
                      "surface", "surface_treatment", "tolerance", "roughness"):
                if features.get(k) is not None:
                    body[k] = features[k]
        return self._request("/dfm", body, "POST")

    def materials(self):
        """材料兼容性查询。

        7862 无 /api/material 端点（实测 404）; 本机材料知识由
        material-surface-linkage skill 的规则库承担。此处如实报告不可用,
        不虚报。
        """
        return {"status": "unavailable",
                "reason": "本机 CNC 内核未提供 /api/material 端点（实测 404）",
                "hint": "材料×表面处理兼容性请用 material-surface-linkage skill"}
    
    def models(self):
        """模型列表"""
        return self._request("/models", None, "GET")


# ═══════════════════════════════════════════════════
# 报价单生成
# ═══════════════════════════════════════════════════
def generate_quote_sheet(quote_result, parse_result=None, dfm_result=None):
    """生成报价单（Markdown格式）"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # 提取数据
    unit_price = quote_result.get("unit_price", 0)
    total_price = quote_result.get("total_price", 0)
    engine = quote_result.get("engine", "unknown")
    lead_time = quote_result.get("lead_time_days", 2)
    breakdown = {}
    if "breakdown" in quote_result:
        bd = quote_result["breakdown"]
        if isinstance(bd, str):
            try:
                bd = json.loads(bd)
            except:
                bd = {}
        breakdown = bd
    # 2026-09-25 修正: :7862 /api/quote 返回的是**平铺字段 + cost_breakdown 子对象**,
    # 从不返回嵌套 "breakdown" (实测 2026-09-25, 45 个顶层字段, 无 breakdown)。
    # 原实现只查 quote_result["breakdown"] → breakdown 恒为 {} → 重量 0.000kg /
    # 体积 0.0cm³ / 工时 0.00h / 利润率仍写死 30%, 且成本表 5 行因 val 全 falsy
    # 而**整块消失** — 报价单看上去像没算过钱。按真实响应兜底合并:
    #   顶层 weight_kg / machine_hours / profit_rate / volume_discount
    #   cost_breakdown: material_cost / machining_cost / surface_cost /
    #                    qc_cost -> 测量费 / (base_fee + setup_cost) -> 其他
    if not breakdown:
        cb = quote_result.get("cost_breakdown")
        if isinstance(cb, str):
            try:
                cb = json.loads(cb)
            except:
                cb = {}
        if not isinstance(cb, dict):
            cb = {}
        breakdown = {
            "weight_kg":        quote_result.get("weight_kg"),
            "machine_hours":    quote_result.get("machine_hours"),
            "profit_rate":      quote_result.get("profit_rate"),
            "quantity_discount": quote_result.get("volume_discount"),
            "material_cost":    cb.get("material_cost"),
            "machining_cost":   cb.get("machining_cost"),
            "surface_cost":     cb.get("surface_cost"),
            "measurement_cost": cb.get("qc_cost"),
            "other_costs":      (cb.get("base_fee") or 0) + (cb.get("setup_cost") or 0),
        }
        breakdown = {k: v for k, v in breakdown.items() if v is not None}

    dims = quote_result.get("dimensions", {})
    material = quote_result.get("material", dims.get("material", "未知"))
    qty = quote_result.get("quantity", dims.get("quantity", 1))
    
    sheet = f"""# 🔧 OPC 报价单

> 生成时间: {now}  
> 报价引擎: {engine}  
> 有效期: 7天

---

## 📋 零件信息

| 项目 | 内容 |
|------|------|
| **材料** | {material} |
| **尺寸** | {dims.get('length','?')}×{dims.get('width','?')}×{dims.get('height','?')} mm |
| **数量** | {qty} 件 |
| **表面处理** | {dims.get('surface', '无')} |
| **公差等级** | {dims.get('tolerance', 'IT8')} |

## 💰 报价

| 项目 | 金额 |
|------|------|
| **单件价格** | ¥{unit_price:.2f} |
| **总价** | **¥{total_price:.2f}** |
| **交期** | {lead_time} 天 |

## 📊 成本分解

| 项目 | 金额 |
|------|------|
"""
    cost_items = [
        ("材料费", breakdown.get("material_cost", 0)),
        ("加工费", breakdown.get("machining_cost", 0)),
        ("表面处理", breakdown.get("surface_cost", 0)),
        ("测量费", breakdown.get("measurement_cost", 0)),
        ("其他", breakdown.get("other_costs", 0)),
    ]
    for label, val in cost_items:
        if val:
            sheet += f"| {label} | ¥{val:.2f} |\n"
    
    _has_vol = breakdown.get("volume_cm3") is not None
    _vol_row = (
        f"| **体积** | {breakdown['volume_cm3']:.1f} cm³ |\n" if _has_vol
        else "| **体积** | — (内核未返回) |\n"
    )
    _hours = breakdown.get("machining_hours", breakdown.get("machine_hours", breakdown.get("cnc_hours")))
    sheet += f"""
## ⚙️ 工艺参数

| 项目 | 参数 |
|------|------|
| **重量** | {breakdown.get('weight_kg', 0):.3f} kg |
{_vol_row}| **加工工时** | {(_hours if _hours is not None else 0):.2f} h |
| **利润率** | {breakdown.get('profit_rate', 0.3)*100:.0f}% |
| **数量折扣** | {breakdown.get('quantity_discount', 1.0)*100:.0f}% |
"""
    
    # DFM结果
    if dfm_result and "issues" in dfm_result:
        sheet += "\n## 🔍 DFM 可制造性分析\n\n"
        issues = dfm_result.get("issues", [])
        if not issues:
            sheet += "✅ 无可制造性问题\n"
        else:
            for issue in issues:
                severity = issue.get("severity", "info")
                icon = "🔴" if severity == "error" else "🟡" if severity == "warning" else "🔵"
                sheet += f"{icon} **{issue.get('title', '')}**: {issue.get('description', '')}\n"
    
    sheet += f"""
---

> 🔗 API: {quote_result.get('api_base', 'http://127.0.0.1:7862/api')}  
> 🤖 模型: nemotron-omni-30b-a3b (本机 vLLM)  
> ⚡ 响应时间: {quote_result.get('duration_ms', 0)} ms
"""
    return sheet


# ═══════════════════════════════════════════════════
# 3D模型生成（可选，依赖 OCP/pythonOCC）
# ═══════════════════════════════════════════════════
def generate_step_model(material, length, width, height, output_path=None):
    """用 OCP 生成 STEP 3D 模型"""
    try:
        from OCP.gp import gp_Pnt, gp_Ax2, gp_Dir
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCP.BRep import BRep_Tool
        from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.TCollection import TCollection_ExtendedString
        
        # 创建长方体
        box = BRepPrimAPI_MakeBox(length, width, height).Shape()
        
        # 写STEP
        if not output_path:
            output_path = f"/tmp/opc_part_{int(time.time())}.step"
        
        writer = STEPControl_Writer()
        writer.Transfer(box, STEPControl_AsIs)
        status = writer.Write(output_path)
        
        if status == IFSelect_RetDone:
            return {"status": "ok", "path": output_path, "message": f"STEP模型已生成: {output_path}"}
        else:
            return {"status": "error", "message": "STEP写入失败"}
    except ImportError:
        return {"status": "skip", "message": "pythonOCC未安装，跳过3D模型生成。运行 setup.sh 安装。"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ═══════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════
def cmd_quote(args):
    """报价命令"""
    client = OPCClient()
    
    print(f"🔗 API: {client.cfg['api_base']}")
    print(f"🔑 Key: {client.key[:15]}...")
    print(f"🤖 Model: {client.model}")
    print()
    
    # 1. 报价
    t0 = time.time()
    result = client.quote(
        material=args.material,
        length=args.length,
        width=args.width,
        height=args.height,
        quantity=args.quantity,
        surface=args.surface,
        tolerance=args.tolerance,
    )
    elapsed = time.time() - t0
    
    if "error" in result:
        print(f"❌ 报价失败: {result['error']}")
        return 1
    
    # 填充额外信息
    result["api_base"] = client.cfg["api_base"]
    result["duration_ms"] = int(elapsed * 1000)
    if "dimensions" not in result:
        result["dimensions"] = {
            "material": args.material,
            "length": args.length,
            "width": args.width,
            "height": args.height,
            "quantity": args.quantity,
            "surface": args.surface,
            "tolerance": args.tolerance,
        }
    elif "material" not in result["dimensions"]:
        result["dimensions"]["material"] = args.material
        result["dimensions"]["quantity"] = args.quantity
    
    # 2. DFM检查（可选）
    dfm_result = None
    if args.dfm:
        dfm_result = client.dfm(
            material=args.material,
            dimensions={"length": args.length, "width": args.width, "height": args.height},
        )
    
    # 3. 3D模型（可选）
    step_result = None
    if args.step:
        step_result = generate_step_model(
            args.material, args.length, args.width, args.height, args.step_output
        )
    
    # 4. 输出
    if args.json:
        output = {"quote": result, "dfm": dfm_result, "step": step_result}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        sheet = generate_quote_sheet(result, None, dfm_result)
        print(sheet)
        if step_result and step_result["status"] == "ok":
            print(f"\n📦 {step_result['message']}")
        elif step_result and step_result["status"] == "skip":
            print(f"\n⚠️ {step_result['message']}")
    
    return 0


def cmd_nl_quote(args):
    """自然语言报价"""
    client = OPCClient()
    
    # 1. 用chat/completions解析自然语言
    nl = args.text
    print(f"📝 输入: {nl}")
    print(f"🔗 API: {client.cfg['api_base']}")
    print()
    
    # 让LLM解析为结构化参数
    parse_prompt = f"""你是CNC报价解析器。将用户输入解析为JSON报价参数。
用户输入: "{nl}"

返回严格JSON格式:
{{
  "material": "材料代码如AL6061",
  "length": 100,
  "width": 50,
  "height": 20,
  "quantity": 1,
  "surface": "表面处理，无则填'无'",
  "tolerance": "公差等级如IT8"
}}

注意:
- 如果用户没说数量，默认1
- 如果用户没说表面处理，填"无"
- 如果用户没说公差，填"IT8"
- 只返回JSON，不要其他文字"""

    chat_result = client.chat([
        {"role": "system", "content": parse_prompt},
        {"role": "user", "content": nl}
    ])
    
    if "error" in chat_result:
        print(f"❌ 解析失败: {chat_result['error']}")
        return 1
    
    # 提取解析结果
    content = chat_result.get("choices", [{}])[0].get("message", {}).get("content", "")
    
    # 尝试提取JSON
    try:
        # 去掉markdown代码块
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        params = json.loads(content)
    except json.JSONDecodeError:
        # 尝试找到JSON部分
        import re
        match = re.search(r'\{[^}]+\}', content, re.DOTALL)
        if match:
            try:
                params = json.loads(match.group())
            except:
                print(f"❌ 无法解析LLM输出: {content}")
                return 1
        else:
            print(f"❌ LLM未返回有效JSON: {content}")
            return 1
    
    print(f"✅ 解析结果: {params.get('material','?')} {params.get('length','?')}×{params.get('width','?')}×{params.get('height','?')}mm x{params.get('quantity',1)}件")
    print()
    
    # 2. 调用报价API
    t0 = time.time()
    result = client.quote(
        material=params.get("material", "AL6061"),
        length=float(params.get("length", 100)),
        width=float(params.get("width", 50)),
        height=float(params.get("height", 20)),
        quantity=int(params.get("quantity", 1)),
        surface=params.get("surface", "无"),
        tolerance=params.get("tolerance", "IT8"),
    )
    elapsed = time.time() - t0
    
    if "error" in result:
        print(f"❌ 报价失败: {result['error']}")
        return 1
    
    result["api_base"] = client.cfg["api_base"]
    result["duration_ms"] = int(elapsed * 1000)
    if "dimensions" not in result:
        result["dimensions"] = params
    
    # 3. 输出
    if args.json:
        print(json.dumps({"parse": params, "quote": result}, ensure_ascii=False, indent=2))
    else:
        sheet = generate_quote_sheet(result)
        print(sheet)
    
    return 0


def cmd_materials(args):
    """列出材料库"""
    client = OPCClient()
    result = client.materials()
    
    if "error" in result:
        print(f"❌ {result['error']}")
        return 1
    
    materials = result if isinstance(result, list) else result.get("materials", result.get("data", []))
    
    print(f"📋 材料库 ({len(materials)}种)")
    print("=" * 60)
    for m in materials:
        if isinstance(m, dict):
            code = m.get("code", m.get("id", m.get("material", "?")))
            name = m.get("name", m.get("material_name", "?"))
            density = m.get("density", m.get("density_g_cm3", "?"))
            price = m.get("price", m.get("ref_price", "?"))
            print(f"  {code:<12} {name:<20} 密度={density} 价格=¥{price}/kg")
        else:
            print(f"  {m}")
    
    return 0


def cmd_health(args):
    """API健康检查"""
    client = OPCClient()
    
    print("🏥 OPC API 健康检查")
    print("=" * 50)
    
    # 测试各端点 — 仅用本机 7862 openapi 实测存在的路径
    #   7862 (CNC 内核): POST /api/quote, POST /api/dfm, GET /api/models
    #   8002 (本地 LLM): POST /v1/chat/completions, GET /v1/models
    #   /api/material 在 7862 不存在 → 已从健康检查移除 (原 404 项)
    tests = [
        ("GET", "/models", None, "本地LLM模型列表 (8002)"),
        ("POST", "/quote", {
            "material": "AL6061", "surface": "无", "surface_treatment": "无",
            "quantity": 1, "weight_kg": 0.05, "max_dim_mm": 50, "tolerance": "IT8",
            "dim_x": 50, "dim_y": 50, "dim_z": 10
        }, "报价 (CNC内核 7862)"),
        ("POST", "/dfm", {
            "material": "AL6061", "dimensions": {"L": 50, "W": 50, "H": 10},
            "min_wall": 1.5
        }, "DFM检查 (7862)"),
        ("POST", "/chat/completions", {
            "model": "nemotron-omni-30b-a3b", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5
        }, "对话 (本地LLM 8002)"),
    ]
    
    all_ok = True
    for method, path, body, label in tests:
        t0 = time.time()
        result = client._request(path, body, method)
        elapsed = (time.time() - t0) * 1000
        
        if "error" in result:
            print(f"  ❌ {label}: {result.get('http_status', 'ERR')} ({elapsed:.0f}ms)")
            all_ok = False
        else:
            print(f"  ✅ {label}: OK ({elapsed:.0f}ms)")
    
    print()
    print(f"API Base: {client.cfg['api_base']}")
    print(f"Status: {'🟢 ALL OK' if all_ok else '🔴 ISSUES'}")
    
    return 0 if all_ok else 1


def main():
    parser = argparse.ArgumentParser(
        description="UnionSkill Quote — API驱动的CNC报价工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 结构化报价
  python3 quote_skill.py quote -m AL6061 -l 100 -w 50 -H 20 -q 10

  # 自然语言报价
  python3 quote_skill.py nl "AL6061方形法兰100x100x15中心孔25四角M8沉头孔 5件"

  # 带DFM检查和3D模型
  python3 quote_skill.py quote -m AL6061 -l 100 -w 50 -H 20 --dfm --step

  # 查看材料库
  python3 quote_skill.py materials

  # API健康检查
  python3 quote_skill.py health
        """
    )
    
    sub = parser.add_subparsers(dest="command")
    
    # quote
    p_q = sub.add_parser("quote", help="结构化报价")
    p_q.add_argument("-m", "--material", required=True, help="材料代码")
    p_q.add_argument("-l", "--length", type=float, required=True, help="长度mm")
    p_q.add_argument("-w", "--width", type=float, required=True, help="宽度mm")
    p_q.add_argument("-H", "--height", type=float, required=True, help="高度mm")
    p_q.add_argument("-q", "--quantity", type=int, default=1, help="数量")
    p_q.add_argument("-s", "--surface", default="无", help="表面处理")
    p_q.add_argument("-t", "--tolerance", default="IT8", help="公差等级")
    p_q.add_argument("--dfm", action="store_true", help="附加DFM检查")
    p_q.add_argument("--step", action="store_true", help="生成STEP 3D模型")
    p_q.add_argument("--step-output", help="STEP输出路径")
    p_q.add_argument("--json", action="store_true", help="JSON输出")
    
    # nl (自然语言)
    p_nl = sub.add_parser("nl", help="自然语言报价")
    p_nl.add_argument("text", help="自然语言描述")
    p_nl.add_argument("--json", action="store_true", help="JSON输出")
    
    # materials
    sub.add_parser("materials", help="查看材料库")
    
    # health
    sub.add_parser("health", help="API健康检查")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    if args.command == "quote":
        return cmd_quote(args)
    elif args.command == "nl":
        return cmd_nl_quote(args)
    elif args.command == "materials":
        return cmd_materials(args)
    elif args.command == "health":
        return cmd_health(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
