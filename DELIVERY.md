# DELIVERY — 交付包说明（GitHub 标准 zip）

> 交付物：`union-export-replica-github-20260928.zip`
> 生成时间：2026-09-28 · 生成方式：`git archive HEAD`（源工作副本）+ 5 项交付修正 · **源工作副本零改动**
> 交付包提交 `ed5432c`（1349 文件）；`scripts/verify_replica.sh` 自检 **PASS（32 通过 / IP·token·API-key 三扫均 0 命中）**。

---

## 1. 这个 zip 是什么

一份**可直接 `git init && gh repo create … --push`** 的公开参赛仓库内容，形态对齐 GitHub
"Download ZIP"：

```
union-export-replica/          ← zip 内唯一顶层目录（解压即仓库根）
├─ README.md  LICENSE  .gitignore
├─ app/  engine/  openclaw/  cnc_inputs/  docs/  env/  models/  ops/  scripts/
└─ （不含 .git / __pycache__ / .ipynb_checkpoints / 权重 / 运行时库）
```

- 内容主体 = 源工作副本 git 仓 **HEAD（1345 个文件）**，即 `1cce766` 提交的全部受跟踪文件 + 第 2 节 4 项新增/豁免 = 1349；
  与原仓逐字节一致（可用 `diff -r <解压目录> <(git archive HEAD | tar -x …)` 复核，仅见第 2 节所列差异）。
- **原始工作副本 `/home/Developer/inference/notebooks/union-export-replica/` 未被修改**：
  所有修正只发生在本交付包内，原程序、原 git 仓、原测试保持原样。

## 2. 相对源工作副本的差异（共 5 处，全部是"让公开仓能跑起来/安全"，不改业务逻辑）

| # | 文件 | 改动 | 为什么 |
|---|------|------|--------|
| 1 | `app/services/credentials.py` | **新增**（原样纳入，未改一行） | 之前被 `.gitignore` 第 12 行 `*credential*` 一刀切挡掉；而 `app/services/gmail_api.py:19`、`gmail_imap.py:20`、`mail_puller.py:32` 在**模块顶层** import 它，`app/services/api_server.py:101` 又无保护地 import `gmail_api` → **别人 clone 后 API server 直接 `ModuleNotFoundError` 起不来，线上 :8051 工作台跟着挂**。该文件本身**不含任何明文密钥**（密钥 = 固定 salt + 机器种子现场派生，凭据只落本机 `app/data/credentials.json`） |
| 2 | `app/tests/test_credentials.py` · `app/tests/fixtures/gbk_nested.zip` | **新增** | 同被 `*credential*` / `*.zip` 误伤；前者是 #1 的单测（凭据重定向 `tmp_path`，不碰本机数据），后者是 GBK 文件名入库测试夹具（758 B，无秘密） |
| 3 | `.gitignore` | 追加 3 条精确豁免 | `!app/services/credentials.py`、`!app/tests/test_credentials.py`、`!app/tests/fixtures/*.zip`。真正敏感的 `app/data/credentials.json` 仍被 `*credential*` + `app/.gitignore:19` **双重**拦截，不会入库 |
| 4 | `scripts/verify_replica.sh` · `ops/GITHUB_PUSH.md` | 重写（去敏） | 原 `verify_replica.sh:26-27` 把**节点公网 IP 和 JupyterLab token 明文**写在会公开的脚本里，且把自己加进扫描白名单，所以自检"PASS"但明文照样发布；`ops/GITHUB_PUSH.md:12` 同样含明文。现在两文件都只用**部分模式串**（token 用 `Timo`+`Spark` 后接 `[0-9A-Za-z]` 由两段变量拼接；
公网 IP 改为**通用 IPv4 扫描**——不写任何节点前缀，因为写前缀等于把前缀本身公开发布），并**删掉白名单**——自检脚本自己也被扫；这些模式串在源码里均由**两段变量拼接**，故脚本不会命中自己 |
| 5 | `engine/完善交付.md` | 脱敏（**打包后在交付包内新发现**） | 该文件的整改日志把 StepFun **真实 API key 的 64 位明文**当"问题证据"引用（P0-3 节），会随公开仓泄露。已改为 `7z5spS…UpZ8T`（仅留头尾标识，不可复原）。**该 key 高度疑似已暴露，推送前请先在 StepFun 后台轮换**。现行 `models.json` 及 `.bak` 的云端项均已用 `${STEPFUN_API_KEY}` 占位，无此问题 |

> 除此之外**没有改动任何应用代码**：33 业务技能、编排、`webui-dist`（与线上 `:8051` md5 一致）、
> 引擎、配置、其余文档全部保持原样。

## 3. 有意不随包分发（及理由）

| 排除项 | 体量/理由 |
|--------|-----------|
| 模型权重（NVFP4，多 GB） | 经 HF 离线缓存挂载，用 `models/MODELS.md` + `models/fetch_and_launch.sh` 复现 |
| conda 环境二进制、`node_modules` | 用 `env/*.yml` + `requirements.txt` 重建 |
| 运行时数据：`engine/data/`（`step` 7.4M + `uploads` 9.7M）、`app/data/*.jsonl|sqlite3|artifacts|mailbox` | "数据留在本地"铁律；`engine/scripts/package_release.py:67-68` 亦按同口径排除 |
| `app/data/credentials.json`、`*.env`、任何 API key | 密钥红线，`.gitignore` + `app/.gitignore` 双重拦截 |
| `tools/`（6.4G 外部工具）、日志、备份 | `app/README.md:58` 已声明 |
| `.git/`、`__pycache__/`、`.ipynb_checkpoints/` | 非交付内容 |

> STEP 输入样例**保留**（`cnc_inputs/step_samples/`），它们是黄金链复现的输入，属仓内容。

## 4. 收到 zip 后怎么验证（3 步）

```bash
unzip union-export-replica-github-20260928.zip && cd union-export-replica
bash scripts/verify_replica.sh                 # 期望 PASS（结构 + 秘密扫描 + 关键文件在位）✅ 32 通过 / 三扫 0 命中

# import 冒烟须在 app 自带环境（见 docs/REPRODUCTION.md 的 conda 环境，含 fastapi / cryptography）里跑：
cd app && python -c "import services.credentials" && echo "CRED IMPORT OK"   # 最关键：修复"clone 即崩"的那个模块
python -m pytest tests/test_credentials.py -q   # 凭据模块单测（可选，7 条；需 pytest + cryptography）
```

复现整条链：`docs/REPRODUCTION.md`、`docs/DEPLOYMENT.md`；交付项与时间线：`docs/SUBMISSION_CHECKLIST.md`；
推送步骤：`ops/GITHUB_PUSH.md`（**建仓/推送需你本人在有账号的终端执行**）。

## 5. 提交前最后一眼（隐私）

```bash
bash scripts/verify_replica.sh                  # 首选：第 2 节扫公网 IPv4(通用) / token / API-key / 个人路径，应全 0 命中
git ls-files | grep -iE 'credential|\.zip$'     # 应只有 3 条源码/夹具，无 data/credentials.json
find . \( -name '*.db' -o -name '*.sqlite3' -o -name '*.env' \) | head   # 应为空
```
