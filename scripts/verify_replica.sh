#!/usr/bin/env bash
# scripts/verify_replica.sh — 复刻包自检：结构 + 秘密/隐私扫描 + 规模清点 + (可选)端口探活
# 退出码 0 = 全部通过；1 = 存在失败项。
#
# 隐私口径（v3, 2026-09-28 交付包修订）:
#   本脚本自身**不含**任何节点 IP / token / API-key 明文——检测用"部分模式串"，
#   且这些串在源码里由两段变量拼接而成（如 "Timo"+"Spark"）：运行时拼成完整检测串，
#   源码中却互不相邻，故本文件不会扫到自己；也**无需/不设白名单**。
#   v3 补齐 v2 的漏洞：v2 只扫 IP 与 token，漏扫了云端 API-key 明文（已在 完善交付.md 发现并补上）。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
FAIL=0; PASS=0
ok(){  echo "  [OK]   $1"; PASS=$((PASS+1)); }
bad(){ echo "  [FAIL] $1"; FAIL=$((FAIL+1)); }

# 检测模式：部分串（可用环境变量覆盖以适配你自己的节点命名）。
# 为不在源码里留下"可被自己扫到的连续明文"，判别串均由两段变量拼接。
#
# IP 检测不绑定任何特定节点前缀（绑定前缀等于把前缀本身写进公开仓）：
# 改为"通用公网 IPv4 明文"扫描，见下方 scan_public_ip（放行私网/回环/链路本地/
# RFC5737 文档段，跳过第三方 minified 构建产物）。
_t1="Timo"; _t2="Spark"                  # token 的判别性片段（两段拼接，源码内不连续、永非完整 token）
# 判别串后要求"紧跟一个字符"：命中真 token（判别串后接年份/编号），又不误命中 .gitignore
# 里"通配符结尾"的文件名防线（STR 后接的是通配符 * ，非 [0-9A-Za-z]，故不命中；示例明文勿写入注释）。
TOK_PATTERN="${UEA_TOKEN_PATTERN:-${_t1}${_t2}[0-9A-Za-z]}"
_k1="penad"; _k2="Pa5BdvyJhr1i"          # 曾泄露的云端 API-key 中部高熵片段（永非完整 key）
KEY_PATTERN="${UEA_KEY_PATTERN:-${_k1}${_k2}}"

echo "== 1) 必需结构 =="
for p in README.md LICENSE .gitignore \
         app/skills app/services app/config app/requirements.txt \
         app/webui-dist/index.html app/webui-dist/assets/index-DSmUweh8.js \
         engine/app engine/environment.yml \
         openclaw/skills cnc_inputs ops/node_services.sh \
         models/MODELS.md models/fetch_and_launch.sh env/README.md \
         docs/REAL_STATE.md docs/NVIDIA_FULLSTACK.md docs/REPRODUCTION.md docs/MANIFEST.md; do
  [ -e "$p" ] && ok "存在 $p" || bad "缺失 $p"
done

# 交付包 v2 新增：曾被 .gitignore 误伤的源码/夹具必须真的在包里（否则 clone 后 import 崩）
for p in app/services/credentials.py app/tests/test_credentials.py app/tests/fixtures/gbk_nested.zip; do
  [ -e "$p" ] && ok "存在 $p" || bad "缺失 $p（clone 后 services.credentials 会 ModuleNotFoundError）"
done

# scan_public_ip: 通用公网 IPv4 明文扫描（不绑定特定节点前缀）。
# 输出命中数到 stdout；命中明细（最多 5 条）到 stderr。
scan_public_ip() {
  python3 - "$ROOT" <<'PYEOF'
import ipaddress, pathlib, re, sys
root = pathlib.Path(sys.argv[1])
# 第三方 minified 构建产物：版本号/常量串会被误判为 IP，跳过
SKIP_PREFIXES = ("app/webui-dist/",)
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2",
            ".ttf", ".step", ".stp", ".zip", ".pdf", ".bin", ".so"}
# 版本号误判："OCP 7.7.2.1" / "v7.7.2.1" 等紧跟 v/ver/version/OCP 的四段数字
VER_CTX = re.compile(r"(?i)(ocp|ver|version|rev|v)\s*$")
ALLOW_NETS = [ipaddress.ip_network(n) for n in
              ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]
IPV4 = re.compile(r"(?<![\d.])(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?![\d.])")
bad = []
for p in sorted(root.rglob("*")):
    if not p.is_file():
        continue
    rel = p.relative_to(root).as_posix()
    if rel.startswith(SKIP_PREFIXES) or p.suffix.lower() in SKIP_EXT or ".git" in p.parts:
        continue
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    for m in IPV4.finditer(txt):
        try:
            ip = ipaddress.ip_address(m.group(1))
        except ValueError:
            continue
        if ip.version != 4 or not ip.is_global or ip.is_multicast:
            continue
        if any(ip in n for n in ALLOW_NETS):
            continue
        if VER_CTX.search(txt[max(0, m.start() - 12):m.start()]):
            continue
        bad.append(f"{rel}: {ip}")
print(len(bad))
for b in bad[:5]:
    print("    " + b, file=sys.stderr)
PYEOF
}

# 个人绝对路径明文扫描（作者本机 / 工作站用户名不得出现在公开仓）
scan_personal_path() {
  python3 - "$ROOT" <<'PYEOF'
import pathlib, re, sys
root = pathlib.Path(sys.argv[1])
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2",
            ".ttf", ".step", ".stp", ".zip", ".pdf", ".bin", ".so"}
# 占位形式放行：<user> / <用户名>；POSIX 放行 DGX 镜像自带账户 Developer 与文档示例 admin
OK_WIN = {"<user>", "<用户名>", "USERNAME", "%USERNAME%"}
OK_NIX = {"<user>", "Developer", "admin", "USER"}
WIN = re.compile(r"[Cc]:[\\/]{1,2}Users[\\/]{1,2}([^\\/\"\s,;:)\]}]+)")
NIX = re.compile(r"/home/([A-Za-z0-9_.\-]+)")
bad = []
for p in sorted(root.rglob("*")):
    if not p.is_file() or p.suffix.lower() in SKIP_EXT or ".git" in p.parts:
        continue
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    rel = p.relative_to(root).as_posix()
    for m in WIN.finditer(txt):
        if m.group(1) not in OK_WIN:
            bad.append(f"{rel}: windows user '{m.group(1)}'")
    for m in NIX.finditer(txt):
        if m.group(1) not in OK_NIX:
            bad.append(f"{rel}: posix home '{m.group(1)}'")
print(len(bad))
for b in bad[:5]:
    print("    " + b, file=sys.stderr)
PYEOF
}

echo "== 2) 秘密/隐私扫描（应 0 命中，含本脚本自身）=="
# grep -I 跳过二进制，-l 只列文件名。模式为"部分串"且源码内不连续，故脚本不自命中；
# 一旦任何文件真泄密（含完整 key/token/IP），此处立即 FAIL。
IPINFO=$(scan_public_ip 2>&1 >/dev/null); IP=$(scan_public_ip 2>/dev/null | head -1)
PATINFO=$(scan_personal_path 2>&1 >/dev/null); PAT=$(scan_personal_path 2>/dev/null | head -1)
TOK=$(grep -rIl "$TOK_PATTERN" . 2>/dev/null | wc -l)
KEY=$(grep -rIl "$KEY_PATTERN" . 2>/dev/null | wc -l)
[ "$IP" = 0 ]  && ok "无公网 IPv4 明文命中（通用扫描）" || bad "发现公网 IPv4 明文（$IP 处）:$IPINFO"
[ "$PAT" = 0 ] && ok "无作者本机用户名/个人路径命中"   || bad "发现个人绝对路径（$PAT 处）:$PATINFO"
[ "$TOK" = 0 ] && ok "无 token 模式命中"          || bad "发现 token 模式命中（$TOK 文件）: $(grep -rIl "$TOK_PATTERN" . 2>/dev/null | head -3 | tr '\n' ' ')"
[ "$KEY" = 0 ] && ok "无云端 API-key 明文命中"     || bad "发现 API-key 明文模式命中（$KEY 文件）: $(grep -rIl "$KEY_PATTERN" . 2>/dev/null | head -3 | tr '\n' ' ')"

echo "== 3) 规模清点 =="
echo "  业务技能(app/skills 目录): $(find app/skills -maxdepth 1 -mindepth 1 -type d 2>/dev/null|wc -l)  |  openclaw 技能(目录): $(find openclaw/skills -maxdepth 1 -mindepth 1 -type d 2>/dev/null|wc -l)  |  STEP 样例: $(find cnc_inputs -name '*.step' 2>/dev/null|wc -l)"
echo "  包大小: $(du -sh . 2>/dev/null|cut -f1)"

echo "== 4) 端口探活（服务在跑时才有效；未启动则跳过）=="
for p in 8888 8002 8011 8902 7862; do
  if curl -fsS "http://127.0.0.1:$p/health" >/dev/null 2>&1 || curl -fsS "http://127.0.0.1:$p/v1/models" >/dev/null 2>&1; then
    ok ":$p UP"
  else
    echo "  [skip] :$p 未探测到（可能未启动）"
  fi
done

echo ""
echo "== 汇总: $PASS 通过, $FAIL 失败 =="
if [ "$FAIL" = 0 ]; then echo "PASS ✅"; exit 0; else echo "FAIL ❌"; exit 1; fi
