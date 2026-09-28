# app/webui-dist — 线上对外工作台（React/Vite 编译版，与 :8051 逐字节一致）

> **这是你在 `http://<NODE_PUBLIC_HOST>:8051` 看到的那个前端。**
> 是 **React + React Router 7.18.4 + Vite** 编译出的单页应用（SPA），product version **`v7.1.0`（livekernel）**。

## 真实性证明（节点实测）

| 文件 | 包内 md5 | 线上 :8051 md5 | 一致 |
|------|----------|----------------|------|
| `index.html`（941B SPA 壳） | — | diff 一致 | ✅ |
| `assets/index-DSmUweh8.js`（1,306,565B 主 bundle） | `d53bdd6d9152760a5bea48e297de618d` | `d53bdd6d9152760a5bea48e297de618d` | ✅ |

> 取证方式：`curl http://<NODE_PUBLIC_HOST>:8051/` 取壳与主 bundle，与 `md5sum` 比对（见 `docs/SUBMISSION_CHECKLIST.md` 与 `docs/MANIFEST.md`）。

## 构成

```
app/webui-dist/
├─ index.html                  # 941B SPA 壳（<div id="root">，引用 /B/assets/*）
├─ favicon.svg  icons.svg
└─ assets/
   ├─ index-DSmUweh8.js        # 主 bundle（含 livekernel / v7.1.0 / 工业非标外贸工作台）
   ├─ index-BHMOvezJ.css       # 样式
   ├─ hero-dashboard-*.png     # 头图
   └─ empty-{orders,mailbox,rag}-*.png   # 空态图
```

## 它怎么连后端

- **资源 base = `/B/`**：壳挂在 `/`，静态资源在 `/B/assets/*`。
- **后端走同源相对 `/v1/*`**（无硬编码 IP/域名）：`/v1/agent/route`、`/v1/agent/task`、
  `/v1/chat/completions`、`/v1/cad/*`、`/v1/cache/stats`、`/v1/config/reload` …
- 脱敏扫描：bundle 内**无**节点 IP / token / 私钥（仅 w3.org、reactjs、reactrouter 的 schema 引用与 `http://localhost` 默认串）。
- `:8051` 位于**另一节点**（50 节点共用同一公网 IP `NODE_PUBLIC_HOST`），本机磁盘不监听 `:8051`，故取其**编译产物**而非源；React 源码 `webui-src/` 本节点不存在。

## 本地忠实预览（可选，非节点既有服务）

把 `webui-dist` 同时挂到 `/`（提供服务壳）与 `/B`（提供 `/B/assets/*`），并把 `/v1/*` 交给运行中的 livekernel（`:8888`）：

```python
# 仅供本地预览：把本文件按需接入你的启动脚本；勿改动节点既有 api_server.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import os
app = FastAPI()
D = os.path.join(os.path.dirname(__file__))          # = app/webui-dist
app.mount("/B", StaticFiles(directory=D), name="B")   # → /B/assets/index-DSmUweh8.js
# 先把业务 /v1/* 路由 include 进来……
# 最后再挂根（mount "/" 放最后，避免遮蔽 /v1 路由）
app.mount("/", StaticFiles(directory=D, html=True), name="root")  # → 提供 index.html
```

> 未起后端时页面能渲染，但 `/v1/*` 请求会报错——先 `bash ops/node_services.sh start` 让 `:8888` 起来即可联动。

## 在 JupyterLab 里查看（最简单，无需额外服务）

直接点开原版 `index.html` 会**白板**——它用**站点根绝对路径** `/B/assets/*`，而 JupyterLab 域名根下没有 `/B`（只服务 `/lab`、`/files`），JS/CSS 全 404 → React 挂不了 → 空 `<div id="root">` + 无样式 → 白板。这恰恰证明它是需要服务器的编译产物。

为此给了一个**相对路径预览版** `index.preview.html`（把资源改成 `./assets/*`）：在 JupyterLab 文件树里**点开它**（走 `/files/` 通道渲染）即可看到界面。

- 打开：`http://<你的:9051>/files/union-export-replica/app/webui-dist/index.preview.html`
- 能渲染整站 UI；但 `/v1/*`（后端）与 `/B/assets/*`（图片）在此通道会 404 → 空态图缺失、数据为空，属正常。
- 要看**联了后端**的真数据：按上面方式把 `webui-dist` 挂到 `/` 与 `/B`，并把 `/v1/*` 反代到 `:8888`。
- **原版 `index.html` 不动**（绝对 `/B`），以维持与 `:8051` 逐字节一致（md5 证据）。

## 与另外两个"静态工作台"的区别（勿混淆）

| 文件 | 技术形态 | 版本 | 是不是线上 :8051 的 UI |
|------|----------|------|------------------------|
| **`app/webui-dist/`（本目录）** | React/Vite 编译 SPA | `v7.1.0` | **✅ 是** |
| `app/webui/index.html` | 单文件静态 HTML/JS（控制台） | v12.0.0-Fusion 等 | ❌ 开发期遗留 |
| `app/index.html` | 单文件静态 HTML（v6 融合版） | v6.1.0 | ❌ 开发期遗留 |

后两者是本节点 `:8888` 默认服务的开发期 UI，本包**如实保留作溯源/回退**，但它们**不是** `:8051` 线上那一个。
