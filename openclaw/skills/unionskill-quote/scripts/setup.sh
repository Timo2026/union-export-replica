#!/usr/bin/env bash
# setup.sh — UnionSkill Quote 本地化装配（零安装版）
#
# 用户指令（2026-09-23）:
#   - 配置本机自有的 API 端点（7862 CNC 内核 / 8002 本地 Omni / 8011 Embed）
#   - 使用本地模型，不外发任何数据（铁律① data-stays-local）
#   - 禁止旁路安装：只能使用 lk-skills 专用 conda env
#
# 本脚本因此:
#   ✗ 不装 pip 包、不装 conda 包、不动系统 Python
#   ✗ 不连任何外部 IP/域名（原 127.0.0.1 / 127.0.0.1 已移除）
#   ✗ 不写明文 API key 到 config.json
#   ✓ 只做"本机端点连通性检查"与"配置文件生成本机化"

set -u

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="/home/Developer/miniconda3/envs/lk-skills/bin/python"
CNC_URL="http://127.0.0.1:7862/api"
LLM_URL="http://127.0.0.1:8002/v1"
EMB_URL="http://127.0.0.1:8011/v1"
MODEL="nemotron-omni-30b-a3b"

echo "╔══════════════════════════════════════════════════╗"
echo "║  UnionSkill Quote — 本机化装配（零安装）          ║"
echo "╚══════════════════════════════════════════════════╝"

# ── 1. 解释器（硬性钉死, 禁止旁路） ──
echo "▶ 检查 lk-skills 专用 env ..."
if [ -x "$PY" ]; then
  echo "  ✅ 解释器: $PY"
  echo "  python: $("$PY" -V 2>&1)"
else
  echo "  ⛔ 未找到 lk-skills env: $PY"
  echo "  ⛔ 铁律: 禁止旁路到其它解释器/环境, 请联系管理员。"
  exit 1
fi

# ── 2. 依赖就绪检查（只检查, 不安装） ──
echo "▶ 检查依赖（只检查, 不安装）..."
if "$PY" -c 'import requests, jinja2' 2>/dev/null; then
  echo "  ✅ requests + jinja2 就绪"
else
  echo "  ⚠️ lk-skills env 缺 requests/jinja2"
  echo "  ⛔ 铁律: 禁止本脚本自行安装。请管理员在 lk-skills env 内补齐后重跑。"
fi
if "$PY" -c 'import OCP' 2>/dev/null; then
  echo "  ✅ pythonOCC (OCP) 就绪"
else
  echo "  ⚠️ OCP 不可用 — STEP 3D 功能降级, 报价功能不受影响"
fi

# ── 3. 本机端点连通性（不外发: 全部 127.0.0.1） ──
echo "▶ 检查本机端点（全部回环, 无外发）..."
_check() {
  local name="$1" url="$2"
  local code
  code=$("$PY" - "$url" <<'PYEOF' 2>/dev/null
import sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=5) as r:
        print(r.status)
except Exception as e:
    print(f"ERR:{type(e).__name__}")
PYEOF
)
  if [ "$code" = "200" ]; then
    echo "  ✅ $name → 200 ($url)"
  else
    echo "  ⚠️ $name → $code ($url)"
  fi
}
_check "CNC 内核 7862" "$CNC_URL/health"
_check "本地 Omni 8002"  "$LLM_URL/models"
_check "本地 Embed 8011" "$EMB_URL/models"

# ── 4. 生成本机化配置（无明文 key） ──
echo "▶ 生成本机化配置..."
cat > "$SKILL_DIR/scripts/config.json" <<EOFCFG
{
    "api_base": "$CNC_URL",
    "llm_base": "$LLM_URL",
    "embed_base": "$EMB_URL",
    "api_key": "local-noauth",
    "model": "$MODEL",
    "timeout": 180,
    "egress": "loopback-only",
    "note": "本机回环端点; 严禁外发 (铁律① data-stays-local)"
}
EOFCFG
echo "  ✅ 配置已生成: $SKILL_DIR/scripts/config.json"

# ── 5. 结论 ──
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  装配完成（零安装 / 零外发 / 零旁路）             ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║  解释器 : $PY"
echo "║  制造数据: $CNC_URL"
echo "║  语言模型: $LLM_URL ($MODEL)"
echo "║  向量检索: $EMB_URL"
echo "║  铁律③  : 草稿模式 — 外部发送由慢轨人工确认"
echo "║"
echo "║  用法（必须用 lk-skills env）:"
echo "║    $PY $SKILL_DIR/scripts/quote_skill.py 'AL6061 100x50x20 10件'"
echo "╚══════════════════════════════════════════════════╝"
