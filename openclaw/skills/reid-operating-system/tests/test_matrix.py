#!/home/Developer/miniconda3/envs/lk-skills/bin/python
"""Reid OS 每周自检脚本 — 验证路由+协议执行+报价集成均正常
用法:
  python3 test_matrix.py              # 完整测试（耗时约90s）
  python3 test_matrix.py --quick      # 快速测试（仅路由+语法，~5s）
"""

import sys
import json
import subprocess
import time
from pathlib import Path

ENGINE = Path.home() / ".openclaw" / "skills" / "reid-operating-system" / "scripts" / "reid_engine.py"
PASS = 0
FAIL = 0
TESTS = []


def run_case(name: str, input_text: str, expect_domain: str = None, expect_type: str = None, quick: bool = False):
    """运行一个测试用例，检查路由结果"""
    global PASS, FAIL
    if quick:
        # 快速模式只检查语法和路径存在
        return

    start = time.time()
    try:
        result = subprocess.run(
            [str(ENGINE), "--input", input_text],
            capture_output=True, text=True, timeout=45
        )
        elapsed = time.time() - start
        output = result.stdout

        # 检查路由
        domain_found = None
        type_found = None
        for line in output.split("\n"):
            if "领域:" in line:
                parts = line.strip().split("|")
                if len(parts) >= 1:
                    domain_found = parts[0].replace("领域:", "").strip()
                if len(parts) >= 2:
                    type_found = parts[1].replace("类型:", "").strip()

        # 检查报价集成
        has_quote = "自动报价" in output or "报价明细" in output or "总价" in output

        # 评估
        ok = True
        reasons = []
        if expect_domain and domain_found != expect_domain:
            ok = False
            reasons.append(f"路由领域期望={expect_domain} 实际={domain_found}")
        if expect_type and type_found and expect_type not in type_found:
            ok = False
            reasons.append(f"路由类型期望={expect_type} 实际={type_found}")
        if result.returncode != 0:
            ok = False
            reasons.append(f"退出码={result.returncode}")

        status = "✅" if ok else "❌"
        duration = f"{elapsed:.1f}s"
        if ok:
            PASS += 1
        else:
            FAIL += 1

        extra = f" [{', '.join(reasons)}]" if reasons else ""
        print(f"  {status} {duration:>6s}  {name}{extra}")
        TESTS.append({"name": name, "ok": ok, "duration": elapsed, "reasons": reasons})

    except subprocess.TimeoutExpired:
        FAIL += 1
        elapsed = time.time() - start
        print(f"  ❌ {elapsed:.1f}s  {name} [超时45s]")
        TESTS.append({"name": name, "ok": False, "duration": elapsed, "reasons": ["超时"]})
    except Exception as e:
        FAIL += 1
        print(f"  ❌  {name} [异常: {e}]")
        TESTS.append({"name": name, "ok": False, "duration": elapsed if 'elapsed' in dir() else 0, "reasons": [str(e)]})


def check_syntax():
    """检查Python语法"""
    global PASS, FAIL
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(ENGINE)],
        capture_output=True, text=True
    )
    ok = result.returncode == 0
    print(f"  {'✅' if ok else '❌'}  语法检查")
    if ok:
        PASS += 1
    else:
        FAIL += 1
    return ok


def check_files():
    """检查所有模板文件存在"""
    global PASS, FAIL
    templates_dir = ENGINE.parent / "templates"
    expected = [
        "triage_prompt.txt", "work_protocol.txt", "family_protocol.txt",
        "daily_protocol.txt", "deep_research_protocol.txt", "quick_qa_protocol.txt",
        "meeting_protocol.txt", "report_protocol.txt", "sandbox_protocol.txt",
        "brainstorm_protocol.txt", "family_education_protocol.txt",
        "family_emotional_protocol.txt", "family_planning_protocol.txt",
        "family_health_protocol.txt", "intervention.txt"
    ]
    all_ok = True
    for f in expected:
        if not (templates_dir / f).exists():
            print(f"  ❌ 模板缺失: {f}")
            all_ok = False
    if all_ok:
        print(f"  ✅  {len(expected)}个模板文件全部存在")
        PASS += 1
    else:
        FAIL += 1
    return all_ok


def check_ollama():
    """检查推理服务和模型"""
    global PASS, FAIL
    # 2026-09-25 修正: 原实现探测 /v1/api/tags (Ollama 端点), 但本机 :8002 是 vLLM —
    # 实测该路径返 HTTP 404 {"detail":"Not Found"}, 于是每次自检必报「缺少模型」假失败
    # (--quick 稳定 2/3)。vLLM 的 OpenAI 兼容探测是 /v1/models (实测 200),
    # 响应形状是 {"object":"list","data":[{"id":...}]}, 不是 Ollama 的 models[].name。
    try:
        result = subprocess.run(
            ["curl", "-s", "http://127.0.0.1:8002/v1/models"],
            capture_output=True, text=True, timeout=5
        )
        d = json.loads(result.stdout)
        models = [m["id"] for m in d.get("data", [])]
        has_qwen = any("nemotron-omni-30b-a3b" in m for m in models)
        if has_qwen:
            print(f"  ✅  vLLM正常 | 模型: {len(models)}个 (含nemotron-omni-30b-a3b)")
            PASS += 1
        else:
            print(f"  ❌  缺少 nemotron-omni-30b-a3b 模型")
            FAIL += 1
    except Exception as e:
        print(f"  ❌  vLLM不可用: {e}")
        FAIL += 1


def main():
    quick = "--quick" in sys.argv

    print("=" * 50)
    print("  Reid OS 系统自检")
    print(f"  {'快速模式' if quick else '完整模式'}")
    print("=" * 50)
    print()

    # Phase 1: 基础设施
    print("[Phase 1/3] 基础设施")
    check_syntax()
    check_files()
    check_ollama()
    print()

    if quick:
        total = PASS + FAIL
        print(f"快速检查结果: {PASS}/{total} 通过, {FAIL} 失败")
        sys.exit(0 if FAIL == 0 else 1)

    # Phase 2: 路由测试
    print("[Phase 2/3] 路由测试")
    run_case("周报汇报", "写周报，本周Sales Ops跟进了23个报价，成交3个", "work", "report")
    run_case("会议纪要", "会议记录：和Matt讨论CRM系统升级方案，销售团队反馈新系统速度快30%", "work", "meeting_minutes")
    run_case("快速问答", "客户说价格太高，怎么回？", "work", "quick_qa")
    run_case("深度分析", "分析一下为什么最近3个月新客户的报价转化率从35%降到了18%", "work", "deep_research")
    run_case("家庭情绪", "垣钧今天在幼儿园哭了，因为想妈妈了", "family", "family_emotional")
    run_case("家庭规划", "考虑要不要二胎，担心经济压力", "family", "family_planning")
    run_case("家庭健康", "孩子有点发烧，不知道要不要去医院", "family", "family_health")
    run_case("家庭教育", "垣钧不想上英语课，说太无聊了", "family", "family_education")
    run_case("沙盘推演", "如果下季度竞争对手降价10%，我们应该怎么应对", "work", "sandbox")
    run_case("报价集成", "法兰盘 50件 6061铝合金 阳极氧化黑色，报个价", "work", None)
    print()

    # Phase 3: 报价检测
    print("[Phase 3/3] 报价集成检测")
    run_case("报价触发-基本", "6061铝合金法兰盘 10件 阳极氧化，报个价", None, None)
    print()

    # 汇总
    total = PASS + FAIL
    print("=" * 50)
    print(f"  结果: {PASS}/{total} 通过, {FAIL} 失败")
    if FAIL == 0:
        print("  状态: ✅ 系统健康")
    else:
        print("  状态: ❌ 需要检查")
    print("=" * 50)

    # 保存结果
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pass": PASS,
        "fail": FAIL,
        "total": total,
        "tests": [{"name": t["name"], "ok": t["ok"], "duration": f"{t['duration']:.1f}s"} for t in TESTS],
        "status": "healthy" if FAIL == 0 else "degraded"
    }
    report_path = Path(__file__).parent / "test_result.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n报告已保存: {report_path}")

    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
