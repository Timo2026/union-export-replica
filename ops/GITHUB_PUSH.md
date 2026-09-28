# GITHUB_PUSH — 把交付包推成公开参赛仓库（需你本人执行）

> 推送属**外发动作**且需要 GitHub 账号，故由你本人在终端执行。
> 本文件**不含**任何节点 IP / SSH 端口 / token 明文（自检命令用"部分模式串"，见 `scripts/verify_replica.sh`）。

## 0. 前置：本目录已是 git 仓

交付包 `union-export-replica/` 已 `git init` 并有提交，`git status` 应为干净。
解压 zip 得到的目录同样可直接推送：

```bash
cd union-export-replica
bash scripts/verify_replica.sh          # 结构 + 秘密扫描，应 PASS（退出码 0）
git log --oneline | head                # 应看到交付提交
```

## 1. 推送前安全自检（务必先跑）

```bash
cd union-export-replica
bash scripts/verify_replica.sh                      # 应 PASS
grep -rIn -e '<SECRET_78dd11a1>\.' . | head         # 应无命中（模式串仅存在于自检脚本）
find . \( -name '*.db' -o -name '*.sqlite3' -o -name '*.env' -o -name 'node.env' \) | head   # 应为空
git ls-files | grep -iE 'credential|\.zip$'         # 应只有源码/测试夹具三条，无 data/credentials.json
```

三条红线（与 `README.md` / `docs/MANIFEST.md` 口径一致）：
1. **不提交** `app/data/credentials.json`、`*.env`、任何 `API_KEY`、模型权重、运行时订单库。
2. **不提交** 节点公网 IP / SSH 端口 / JupyterLab token。
3. `app/services/credentials.py` 是**无密钥源码**（密钥由固定 salt + 机器种子现场派生，凭据只落本机
   `app/data/credentials.json`），已随包发布；`app/.gitignore` 依旧拦住真正的凭据数据文件。

## 2. 建仓并推送

```bash
# GitHub CLI（推荐，自动建公开仓并推送）
gh repo create union-export-replica --public --source=. --remote=origin --push

# 或：网页建空仓后接 remote 推送
#   git remote add origin git@github.com:<你的账号>/union-export-replica.git
#   git push -u origin main
```

推送成功后，`https://github.com/<你的账号>/union-export-replica` 即提交清单第 1 项的 URL。

## 3. 交付物清单

- 本 zip：`union-export-replica-github-20260928.zip`（= GitHub "Download ZIP" 形态：单顶层目录、无 `.git`、无 `__pycache__`/`.ipynb_checkpoints`、无权重与运行时库）。
- 说明：`DELIVERY.md`（本包相对源工作副本的差异、有意排除项及理由）。
- 复现：`docs/REPRODUCTION.md`、`docs/DEPLOYMENT.md`；自检：`scripts/verify_replica.sh`。

## 4. 隐私红线（再次确认）

- 码云备选：网页建仓后 `git remote add origin https://gitee.com/<账号>/union-export-replica.git && git push -u origin main`。
- 若你为自己的节点改写自检模式串，只改环境变量 `UEA_IP_PATTERN` / `UEA_TOKEN_PATTERN`，**不要把明文写回任何入库文件**。
