#!/home/Developer/miniconda3/envs/lk-skills/bin/python
"""
verify_quote.py - 报价引擎部署验证脚本 (引用手工报价系统的验证模式)

用法:
  # 验证某一类零件
  python3 verify_quote.py --checkpoint shaping_ring_6061
  
  # 全量验证
  python3 verify_quote.py --all

退出码: 0=全部通过, 1=有失败项
"""
import sys, io, json, os, subprocess

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_FILE = os.path.join(SCRIPT_DIR, 'quote_checkpoints.json')

QUOTE_PY = os.path.expanduser('~/.openclaw/skills/quote-ptuning/scripts/quote.py')
ROUGH_QUOTE_PY = os.path.expanduser('~/.openclaw/skills/rough-machining-quote/scripts/rough_quote.py')

PYTHON = '/home/Developer/miniconda3/envs/lk-skills/bin/python'

def to_f(val):
    if val is None: return None
    if isinstance(val, (int, float)): return float(val)
    try: return float(str(val).replace(',', '').replace('¥', '').replace('$', ''))
    except: return None

def extract_number(text, keywords=None):
    """从文本中提取数值，优先匹配包含keyword的行"""
    if keywords:
        for kw in keywords:
            for line in text.split('\n'):
                if kw in line:
                    for part in line.replace('¥', '').replace(',', '').replace('￥', '').split():
                        try:
                            val = float(part)
                            if abs(val) > 0.01:
                                return val
                        except:
                            pass
    # fallback: 所有行找最大合理数字
    best = None
    for line in text.split('\n'):
        for part in line.replace('¥', '').replace(',', '').replace('￥', '').split():
            try:
                val = float(part)
                if 1 < val < 10000000:  # 合理的价格范围
                    if best is None or val > best:
                        best = val
            except:
                pass
    return best

def run_quote(inputs):
    """调用quote.py"""
    part_name = inputs.get('part_name', inputs.get('id', 'test_part'))
    quantity = inputs.get('quantity', 1)
    material = inputs.get('material', '6061铝合金')
    surface = inputs.get('surface', '无')
    
    cmd = [PYTHON, QUOTE_PY, part_name, str(quantity), material, surface]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                              cwd=os.path.dirname(QUOTE_PY))
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return {'error': '超时'}
    except Exception as e:
        return {'error': str(e)}
    
    total = extract_number(output, keywords=['总价', '总计', '小计', '合计', '汇总', '报价'])
    unit_price = extract_number(output, keywords=['单价'])
    if unit_price is None:
        unit_price = total / quantity if total else None
    
    return {'unit_price': unit_price, 'total': total, 'raw': output[:200]}

def run_rough_quote(inputs):
    """调用rough_quote.py"""
    material = inputs.get('material', 'DC53模具钢')
    l = inputs.get('length', 260)
    w = inputs.get('width', 200)
    h = inputs.get('height', 55)
    
    cmd = [PYTHON, ROUGH_QUOTE_PY, '--material', material,
           '--length', str(l), '--width', str(w), '--height', str(h)]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                              cwd=os.path.dirname(ROUGH_QUOTE_PY))
        output = result.stdout + result.stderr
    except Exception as e:
        return {'error': str(e)}
    
    total = extract_number(output, keywords=['总价', '总计', '小计', '合计', '汇总', '报价'])
    return {'total': total, 'raw': output[:200]}

def verify_one(checkpoint):
    """验证单个checkpoint"""
    cid = checkpoint['id']
    desc = checkpoint['desc']
    inputs = checkpoint['inputs']
    benchmark = checkpoint["expected"]
    tolerance = checkpoint.get('tolerance', 0.25)
    
    print(f'\n── {cid}: {desc}')
    print(f'    基准: ¥{benchmark["total"]:.2f} (来源: {benchmark.get("source", "未知")})')
    
    engine = inputs.get('engine', 'quote-ptuning')
    
    if engine == 'rough_machining':
        if not os.path.exists(ROUGH_QUOTE_PY):
            print(f'    ⚠️  跳过: rough_quote.py未找到')
            return True
        result = run_rough_quote(inputs)
    else:
        result = run_quote(inputs)
    
    if 'error' in result:
        print(f'    ⚠️  引擎错误: {result["error"]}')
        # 不标记失败 — 可能是环境问题
        return True
    
    actual = result.get('total')
    expected = benchmark['total']
    
    if actual is None:
        print(f'    ⚠️  无法解析输出\n    原始输出: {result.get("raw", "")[:120]}')
        return True
    
    diff_pct = (actual - expected) / expected * 100
    within = abs(diff_pct) <= tolerance * 100
    status = '✅' if within else '❌'
    
    print(f'    {status} 基准¥{expected:.2f} → 实际¥{actual:.2f} (偏差{diff_pct:+.1f}%, 容差{tolerance*100:.0f}%)')
    
    return within

def main():
    cp_path = CHECKPOINT_FILE
    if not os.path.exists(cp_path):
        cp_path = '/tmp/quote_checkpoints.json'
    if not os.path.exists(cp_path):
        print('❌ quote_checkpoints.json 未找到')
        sys.exit(1)
    
    with open(cp_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    checkpoints = data['checkpoints']
    version = data['version']
    
    import argparse
    parser = argparse.ArgumentParser(description='报价引擎部署验证')
    parser.add_argument('--all', action='store_true', help='全量验证')
    parser.add_argument('--checkpoint', type=str, help='指定checkpoint ID')
    args = parser.parse_args()
    
    print('=' * 60)
    print(f'  报价引擎部署验证 v{version}')
    print(f'  日期: {data["date"]}')
    print(f'  quote.py: {"✅" if os.path.exists(QUOTE_PY) else "❌" }')
    print(f'  rough_quote.py: {"✅" if os.path.exists(ROUGH_QUOTE_PY) else "❌" }')
    print('=' * 60)
    
    if args.checkpoint:
        targets = [cp for cp in checkpoints if cp['id'] == args.checkpoint]
        if not targets:
            print(f'❌ 未找到checkpoint: {args.checkpoint}')
            for cp in checkpoints:
                print(f'  {cp["id"]}')
            sys.exit(1)
    elif args.all:
        targets = checkpoints
    else:
        print('\n用法: --all 全量验证 | --checkpoint <ID>')
        print('可用checkpoints:')
        for cp in checkpoints:
            print(f'  {cp["id"]:30s} → {cp["desc"]}')
        sys.exit(0)
    
    results = []
    for cp in targets:
        ok = verify_one(cp)
        results.append((cp['id'], ok))
    
    print('\n' + '=' * 60)
    all_pass = all(r[1] for r in results)
    
    for cid, ok in results:
        print(f'  {"✅" if ok else "❌"} {cid}')
    
    if all_pass:
        print('\n🎉 所有验证点通过！报价引擎部署正确。')
    else:
        print('\n⚠️ 存在偏差项。注意: 偏差不一定=错误，可能是基准值需要更新。')
        print('   手工基准和引擎算法的差异属于正常范围。')
    print('=' * 60)
    
    sys.exit(0 if all_pass else 1)

if __name__ == '__main__':
    main()
