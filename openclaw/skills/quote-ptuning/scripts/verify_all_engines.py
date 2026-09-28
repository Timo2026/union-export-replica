#!/home/Developer/miniconda3/envs/lk-skills/bin/python
"""
verify_all_engines.py — 全引擎报价部署验证 (引用手工报价系统verify.py模式)

覆盖三个报价引擎：
  1. quote-ptuning (1.0)
  2. nonstandard-reasoning-quote (3.0)
  3. rough-machining-quote

用法:
  --all                    全量验证 (5个零件 × 引擎)
  --engine <name>          只验某个引擎: ptuning|reasoning|rough
  --checkpoint <id>        只验某个零件
  --update                 用当前引擎输出更新checkpoints
  --help                   帮助

退出码: 0=全部通过, 1=有失败
"""
import sys, io, json, os, subprocess, re, argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_FILE = os.path.join(SCRIPT_DIR, 'quote_checkpoints.json')

HOME   = os.path.expanduser('~')
PYTHON = '/home/Developer/miniconda3/envs/lk-skills/bin/python'
QUOTE_PY     = f'{HOME}/.openclaw/skills/quote-ptuning/scripts/quote.py'
REASONING_PY = f'{HOME}/.openclaw/skills/nonstandard-reasoning-quote/scripts/reasoning_quote.py'
ROUGH_PY     = f'{HOME}/.openclaw/skills/rough-machining-quote/scripts/rough_quote.py'

ENGINE_LABELS = {
    "ptuning":   "📐 quote-ptuning",
    "reasoning": "🧠 reasoning-quote 3.0",
    "rough":     "⚙️ rough-machining"
}

TEST_CASES = [
    {
        "id": "shaping_ring_6061",
        "desc": "ShapingRing(91×5×81.2mm, 6061, 阳极氧化, ×3)",
        "engines": {
            "ptuning": {
                "cmd": [PYTHON, QUOTE_PY, "ShapingRing", "3", "6061铝合金", "阳极氧化"],
                "cwd": os.path.dirname(QUOTE_PY)
            },
            "reasoning": {
                "cmd": [PYTHON, REASONING_PY, "--material", "6061铝合金",
                        "--dimensions", "91x5x81.2", "--surface", "阳极氧化",
                        "--quantity", "3", "--samples", "3", "--json"],
                "cwd": os.path.dirname(REASONING_PY)
            }
        },
        "expected": {
            "ptuning":   {"total": 515.62, "tolerance": 0.10},
            "reasoning": {"total": None, "tolerance": 0.30}
        }
    },
    {
        "id": "shaft_c_45steel",
        "desc": "轴C(151×44×392mm, 45钢, 发黑, ×1)",
        "engines": {
            "ptuning": {
                "cmd": [PYTHON, QUOTE_PY, "轴C", "1", "45钢", "发黑"],
                "cwd": os.path.dirname(QUOTE_PY)
            },
            "reasoning": {
                "cmd": [PYTHON, REASONING_PY, "--material", "45钢",
                        "--dimensions", "151x44x392", "--surface", "发黑",
                        "--quantity", "1", "--samples", "3", "--json"],
                "cwd": os.path.dirname(REASONING_PY)
            }
        },
        "expected": {
            "ptuning":   {"total": 120.31, "tolerance": 0.10},
            "reasoning": {"total": 1358.13, "tolerance": 0.30}
        }
    },
    {
        "id": "punch_dc53",
        "desc": "下冲(260×200×55mm, DC53, 无, ×1)",
        "engines": {
            "ptuning": {
                "cmd": [PYTHON, QUOTE_PY, "下冲", "1", "DC53模具钢", "无"],
                "cwd": os.path.dirname(QUOTE_PY)
            },
            "reasoning": {
                "cmd": [PYTHON, REASONING_PY, "--material", "DC53模具钢",
                        "--dimensions", "260x200x55", "--surface", "无",
                        "--quantity", "1", "--samples", "3", "--json"],
                "cwd": os.path.dirname(REASONING_PY)
            }
        },
        "expected": {
            "ptuning":   {"total": 343.75, "tolerance": 0.10},
            "reasoning": {"total": 904.65, "tolerance": 0.30}
        }
    },
    {
        "id": "flange_6061",
        "desc": "法兰(120×80×10mm, 6061, 阳极氧化, ×1)",
        "engines": {
            "ptuning": {
                "cmd": [PYTHON, QUOTE_PY, "法兰", "1", "6061铝合金", "阳极氧化"],
                "cwd": os.path.dirname(QUOTE_PY)
            },
            "reasoning": {
                "cmd": [PYTHON, REASONING_PY, "--material", "6061铝合金",
                        "--dimensions", "120x80x10", "--surface", "阳极氧化",
                        "--quantity", "1", "--samples", "3", "--json"],
                "cwd": os.path.dirname(REASONING_PY)
            }
        },
        "expected": {
            "ptuning":   {"total": 171.88, "tolerance": 0.10},
            "reasoning": {"total": 491.63, "tolerance": 0.30}
        }
    },
    {
        "id": "rough_punch_dc53",
        "desc": "开粗(260×200×55mm, DC53, 无)",
        "engines": {
            "rough": {
                "cmd": [PYTHON, ROUGH_PY, "DC53", "260×200×55"],
                "cwd": os.path.dirname(ROUGH_PY)
            }
        },
        "expected": {
            "rough": {"total": 3765.83, "tolerance": 0.10}
        }
    }
]

# ============================================================

def extract_number(text, keywords=None):
    """智能提取输出中的价格数字"""
    vals = []
    for line in text.split('\n'):
        line_clean = line.replace('¥', '').replace('￥', '').replace(',', '').strip()
        for part in line_clean.split():
            try:
                v = float(part)
                if 0.01 < v < 10000000:
                    vals.append((v, line))
            except:
                pass
    if keywords:
        for kw in keywords:
            for v, line in vals:
                if kw in line:
                    return v
    return max([v for v, _ in vals]) if vals else None

def run_engine(engine_key, test_case):
    """运行一个引擎并返回(total, raw_output, confidence)"""
    engine_conf = test_case['engines'].get(engine_key)
    if not engine_conf:
        return None, "引擎未配置", 0
    
    try:
        result = subprocess.run(
            engine_conf['cmd'],
            capture_output=True, text=True, timeout=60,
            cwd=engine_conf.get('cwd')
        )
        output = (result.stdout or '') + (result.stderr or '')
    except subprocess.TimeoutExpired:
        return None, "超时(>60s)", 0
    except Exception as e:
        return None, str(e), 0
    
    # 3.0引擎输出JSON -> 直接解析
    if engine_key == 'reasoning':
        try:
            json_match = re.search(r'\{.*"unit_price_mean".*\}', output, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                if 'unit_price_mean' in data:
                    return data['unit_price_mean'], output, data.get('cv_percent', 0)
        except:
            pass
    
    total = extract_number(output, keywords=['总价', '总计', '小计', '合计', '汇总', '均价'])
    return total, output, None

def verify_one_engine(engine_key, test_case):
    """运行并验证单个引擎×单个零件"""
    expected_info = test_case['expected'].get(engine_key)
    if not expected_info:
        return True  # 跳过未配的
    
    total, raw, conf = run_engine(engine_key, test_case)
    expected = expected_info['total']
    tolerance = expected_info['tolerance']
    label = ENGINE_LABELS.get(engine_key, engine_key)
    
    if total is None:
        if expected is None:
            print(f'     {label}: ⏳ 无基准值 (跳过, raw={raw[:80]})')
            return True
        print(f'     {label}: ❌ 执行失败 ({raw[:60]})')
        return False
    
    if expected is None:
        print(f'     {label}: 💡 ¥{total:.2f} (无基准, 跳过校验, CV={conf}%)')
        return True
    
    diff_pct = (total - expected) / expected * 100
    within = abs(diff_pct) <= tolerance * 100
    status = '✅' if within else '❌'
    extra = f' CV={conf}%' if conf else ''
    print(f'     {label}: {status} 基准¥{expected:.2f} → 实际¥{total:.2f} ({diff_pct:+.1f}%){extra}')
    return within

def main():
    parser = argparse.ArgumentParser(description='报价引擎跨引擎验证工具')
    parser.add_argument('--all', action='store_true', help='全量验证')
    parser.add_argument('--engine', type=str, help='只验某个引擎')
    parser.add_argument('--checkpoint', type=str, help='只验某个零件ID')
    parser.add_argument('--update', action='store_true', help='更新基准值')
    parser.add_argument('--version', action='store_true', help='版本信息')
    args = parser.parse_args()
    
    if args.version:
        print('verify_all_engines.py v1.0')
        sys.exit(0)
    
    print('=' * 60)
    print('  报价引擎验证系统 (引用手工报价系统verify.py)')
    print('=' * 60)
    for k, label in ENGINE_LABELS.items():
        p = {'ptuning': QUOTE_PY, 'reasoning': REASONING_PY, 'rough': ROUGH_PY}[k]
        print(f'  {label}: {"✅" if os.path.exists(p) else "❌"}')
    print()
    
    targets = TEST_CASES
    if args.checkpoint:
        targets = [t for t in TEST_CASES if t['id'] == args.checkpoint]
        if not targets:
            print(f'❌ 未找到checkpoint: {args.checkpoint}')
            sys.exit(1)
    
    engines_to_test = ['ptuning', 'reasoning', 'rough']
    if args.engine:
        engines_to_test = [args.engine]
    
    all_pass = True
    for tc in targets:
        print(f'── {tc["id"]}: {tc["desc"]}')
        for ek in engines_to_test:
            ok = verify_one_engine(ek, tc)
            if not ok:
                all_pass = False
        print()
    
    print('=' * 60)
    if all_pass:
        print('🎉 所有测试通过！')
    else:
        print('⚠️ 存在偏差项 (可能正常, 需人工判断)')
    print('=' * 60)
    sys.exit(0 if all_pass else 1)

if __name__ == '__main__':
    main()
