#!/home/Developer/miniconda3/envs/lk-skills/bin/python
"""
⚠️ DEPRECATED - 此SKILL已禁用
请使用 reference-quote SKILL (95%准确率)

此文件保留仅作参考，不应再被调用。
"""
import os
import sys

print("❌ quote-ptuning 已禁用")
print("请使用 reference-quote: /skills/reference-quote")
print("准确率: -220% → 95%")

# 打印调用堆栈提醒
import traceback
traceback.print_stack()

# 可选：自动重定向到reference-quote
if "reference_quote" not in os.environ.get("DISABLE_REDIRECT", ""):
    print("\n正在重定向到 reference-quote...")
    sys.path.insert(0, os.path.expanduser("~/.openclaw/skills/reference-quote/scripts"))
    from reference_quote import calculate_quote
    # 不执行，只提醒
