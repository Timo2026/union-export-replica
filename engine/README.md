<p align="center">
  <img src="https://img.shields.io/badge/version-12.0.0--fusion-6366f1?style=for-the-badge" alt="Version">
  <img src="https://img.shields.io/badge/python-3.11+-blue?style=for-the-badge&logo=python" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" alt="License">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey?style=for-the-badge" alt="Platform">
</p>

<h1 align="center">🏭 Union·由你 — CNC AI 工艺大脑 v12.0.0-fusion</h1>

<p align="center">
  <strong>一句话画图 · 3D 预览 · 上传报价 · 一键输出打包</strong><br>
  AI 驱动的 CNC 加工报价与工艺规划系统 · 离线自持 · 多模型自适应
</p>

---

## 📖 目录

- [项目简介](#项目简介)
- [核心特性](#核心特性)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [API 概览](#api-概览)
- [项目结构](#项目结构)
- [模型配置](#模型配置)
- [MTClaw Function Router 集成](#mtclaw-function-router-集成)
- [DFM 特征实测闭环（C1-C6）](#dfm-特征实测闭环c1-c6)
- [技术栈](#技术栈)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

---

## 项目简介

**Union·由你** 是一个 AI 驱动的 CNC 加工智能报价与工艺规划系统。上传图纸或描述零件需求，系统自动完成：

1. 🧠 **意图识别** — MTClaw Function Router 关键词预过滤 + LLM 路由
2. 📐 **3D 生成** — TOT（Tree-of-Thought）三管道竞争，选优生成 STEP/STL
3. 🔍 **冲突检测** — DFM 工艺可行性检查（材料/表面处理/公差/热处理）
4. 💰 **智能报价** — 8 种材料 × 9 种表面处理，精度/五轴/线切割附加费自动计算
5. 📦 **一键打包** — STEP + STL + XLSX 报价单 + JSON 规格书，ZIP 导出

**设计哲学**：离线优先、多模型自适应、规则引擎兜底——断网也能跑。

---

## 核心特性

### 🤖 TOT 三管道竞争生成

| 管道 | 引擎 | 权重 | 说明 |
|------|------|------|------|
| LLM | Qwen / GPT | 0.30 schema + 0.30 coverage | 大模型理解自然语言生成参数 |
| 正则 | Python 规则 | 0.25 geometry + 0.15 bbox | 确定性解析，0ms 延迟 |
| 知识库 | SQLite RAG | 同上 | 历史订单语义匹配 |

三管道并行运算 → 打分陪审团选出最优 → OCC 生成正式 STEP（非优胜者临时文件自动清理）。

### 💰 即时报价引擎

- **8 种材料**：45钢 / Q235 / 6061 / 7075 / 304 / 316L / TC4 / 黄铜（含别名归一，如 45#→45钢、sus304→304、al6061→6061、h59→黄铜、钛合金→TC4）
- **9 种表面处理**：无 / 发黑 / 阳极氧化 / 镀锌 / 镀铬 / 镀镍 / 磷化 / 喷漆 / 喷砂
- **附加费自动计算**：精度等级（IT4-IT10）、五轴加工（1.8×）、线切割（1.2×）
- **v3.0 Excel 公式还原** ：材料费 + 加工费 + 表面处理费 → 含利润总价

> 以上数字基于 `src/runtime/quote_adapter.py` 的 `_MATERIALS` 与 `_SURF_COEFS` 实测。

### 🛡️ 优雅降级链

```
本地 LLM 可用？ → 直接用
        ↓ 不可用
云端 API 可用？ → 转发到云端
        ↓ 不可用
本地规则引擎   → 纯数学计算（离线兜底，永远可用）
```

### 🔗 MTClaw Function Router 集成

CNC 垂域工具加速层，将高频操作（报价计算、冲突检测）转化为本地 Python 函数调用：

- **/api/cnc-quick** — 冲突检测 + 报价一体化（< 50ms，纯规则）
- **/api/cnc-intent** — 意图识别端点（供 MTClaw FR 调用）
- `cnc_functions.jsonl` — OpenAI Function Calling 格式工具定义

> 通用 LLM 对话走 MTClaw FR 路由到上游模型；CNC 报价/冲突检测走本地脚本毫秒级返回，不消耗 token。

### 📋 更多特性

- **多格式解析**：PDF / DWG / DXF / XLSX / ZIP 上传，PaddleOCR + MiMO VLM 视觉理解
- **3D 实时预览**：Three.js WebGL 渲染 STEP/STL
- **DFM 冲突检测**：材料 × 表面处理 × 公差 × 热处理禁忌矩阵
- **模型自动发现**：环境变量配置 12+ 云端 API + Ollama 本地检测，按 quality_score 排序
- **可解释推理链**：ReasoningChain 记录每一步推理过程（SHA-256 哈希审计链）
- **历史回溯**：SQLite 存储历史订单，语义匹配复用
- **Shadow Mode**：AI 建议标注免责声明，人工确认制

### 📊 能力矩阵（已实现 vs 规划中）

> 如实标注，区分 `src/` 代码已落地与未来目标，避免虚标。

| 能力 | 状态 | 证据 / 说明 |
|------|------|-------------|
| TOT 三管道竞争生成 | ✅ 已实现 | `src/runtime/step_generator_dual.py`（LLM / 正则 / 知识库并行打分选优） |
| 5 专家串行会议 | ✅ 已实现 | `src/neuro_core/serial_expert.py`（工艺/材料/报价/DFM/审计五专家） |
| SHA-256 审计链 | ✅ 已实现 | `src/neuro_core/reasoning_chain.py`（每步推理哈希上链） |
| DFM 冲突检测 | ✅ 已实现 | `src/neuro_core/conflict_check.py`（材料×表面处理×公差×热处理禁忌矩阵） |
| 即时报价引擎 | ✅ 已实现 | `src/runtime/quote_adapter.py`（8 材料 × 9 表面处理，纯数学） |
| STEP 生成 | ✅ 已实现 | `src/runtime/step_generator.py` + OCC/trimesh 双引擎 |
| 一键打包导出 | ✅ 已实现 | `src/runtime/export_bundler.py`（STEP+STL+XLSX+JSON → ZIP） |
| 模型自动发现 | ✅ 已实现 | `src/core/model_auto_loader.py` + `model_registry.py`（按 quality_score 排序） |
| AMD ROCm 原生推理 | 🚧 已提供部署支持（本地未实测） | 已提供 `docker-compose.rocm.yml` + 参数化 `Dockerfile`（rocm/pytorch）；本地实测后端仍为摩尔线程 MUSA M1000（vLLM MUSA） |
| 24+ 材料库扩展 | 🚧 规划中 | 当前 8 种材料（含别名归一），后续按订单数据扩展 |
| DFM 特征实测闭环 | ✅ 已实现 | `feature_extractor.py` + `dfm_advisor.py` + `tool_selector.py` + `quote_explainer.py`（C1-C6 六阶段流水线，60 测试全绿） |

### 🔬 DFM 特征实测闭环（C1-C6）

上传 STEP 后系统自动跑完 **C1→C6 六阶段流水线**，从"缺特征不评分"变为"基于真实几何判定 + 白盒报价 + 一键打包"：

| 阶段 | 模块 | 产出 | 测试 |
|------|------|------|------|
| **C1** 特征实测 | `feature_extractor.py` | 孔/壁厚/圆角/锥面/平面面积（OCP 拓扑遍历） | 13 |
| **C2** DFM 微调建议 | `dfm_advisor.py` | 结构化修改建议（severity/action_type） | 15 |
| **C3** 刀具审核 | `tool_selector.py` | 刀具清单（钻头/丝锥/沉头刀） | 13 |
| **C4** 最终报价 | `quote_adapter.py` | 带真实特征的三路收敛报价 | 6 |
| **C5** 白盒说明 | `quote_explainer.py` | 逐项费用拆解（公式+数值） | 5 |
| **C6** ZIP 打包 | `export_bundler.py` | 10 个产物 JSON + STEP 原件 | 8 |

**核心突破**：DFM `missing_fields` 从 `['min_wall','hole_d','hole_depth']` → `[]`，`dfm_score` 从 `None` → 基于真实几何评分。

---

## 系统架构

```
                         ┌─────────────────────────┐
                         │    用户 / 前端界面       │
                         │  Three.js 3D · Web UI   │
                         └───────────┬─────────────┘
                                     │ HTTP :7862
                         ┌───────────▼─────────────┐
                         │   FastAPI 主服务        │
                         │   app/main.py           │
                         └───┬───────┬───────┬─────┘
                  ┌──────────▼┐ ┌───▼───┐ ┌─▼──────────┐
                  │ CNC Quick │ │  TOT  │ │  上传/导出   │
                  │  快速通道  │ │ 管道  │ │  打包模块    │
                  └────┬──────┘ └───┬───┘ └─────────────┘
                       │            │
         ┌─────────────▼────────────▼─────────────┐
         │         MTClaw Function Router         │
         │         :7863  (工具加速层)             │
         │  ┌──────────┐  ┌───────────────────┐   │
         │  │ 冲突检测  │  │     报价计算      │   │
         │  │ < 50ms   │  │     < 50ms       │   │
         │  └──────────┘  └───────────────────┘   │
         └──────────────────┬─────────────────────┘
                            │ 非 CNC 请求 → 透明转发
                ┌───────────▼───────────┐
                │    上游 LLM 模型       │
                │  Qwen3-8B GPTQ MUSA  │
                │  Qwen3.6-35B LMStudio │
                │  GPT-OSS-120B         │
                │  Step-3.7-Flash 云端  │
                └───────────────────────┘

降级顺序: MTClaw FR :7863 → 云端 API → 本地 LLM → 规则引擎(离线兜底)
```

---

## 快速开始

### 环境要求

- **Python** ≥ 3.11
- **操作系统**：Windows 10+ / Linux（Ubuntu 22.04+）
- **可选**：Ollama（本地模型）、LMStudio（本地 LLM服务器）

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/timocao/CNC-AI-Brain.git cnc-ai-brain
cd cnc-ai-brain

# 2A. 创建 conda 环境（推荐，支持 STEP 精确解析）
conda env create -f environment.yml
conda activate step-render

# 2B. 或创建 venv（精简，仅规则引擎报价）
python -m venv .venv
.venv\Scripts\activate          # Windows
set PYTHONUTF8=1                # Windows 避免 GBK 编码
pip install -r requirements.txt

# 3. (可选) 安装 Ollama
ollama pull qwen2.5:1.5b
```

### 启动

```bash
# 完整模式（conda step-render，支持 STEP 上传 + 3D 预览）
conda activate step-render
python -m uvicorn app.main:app --host 127.0.0.1 --port 7862

# 精简模式（零依赖，纯数学报价）
python app/main_lite.py

# 或一键启动（自动检测 conda 环境）
CNC_AI_Brain_启动.bat          # Windows
```

打开浏览器访问 **http://127.0.0.1:7862**

### 启动 MTClaw Function Router（可选）

```bash
# 在另一个终端
cd C:\Users\<用户名>\.function-router
start_fr.bat                   # Windows
# ./start_fr.sh                # Linux
```

FR 启动后，CNC 报价和冲突检测请求将走本地工具加速路径，不消耗 LLM token。

---

## API 概览

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | Web UI 主页（Three.js 3D 预览） |
| `/api/health` | GET | 健康检查 |
| `/api/cnc-quick` | POST | CNC 冲突检测 + 报价一体化快速通道 |
| `/api/cnc-intent` | POST | CNC 意图识别（供 MTClaw FR 调用） |
| `/api/upload` | POST | 图纸上传（STEP/PDF/DWG/DXF/XLSX/ZIP），自动触发 C1 特征实测 |
| `/api/parts/{id}/features` | POST | C1 特征实测端点（OCP 拓扑遍历提取孔/壁厚/圆角） |
| `/api/quote` | POST | 报价计算 |
| `/api/conflict-check` | POST | 工艺冲突检测 |
| `/api/export` | POST | STEP + STL + XLSX 打包导出 |
| `/api/history` | GET | 历史订单查询 |
| `/api/audit` | GET | SHA-256 审计链查询 |
| `/api/rag/search` | POST | 知识库检索 |
| `/docs` | GET | Swagger API 文档 |

### 快速报价示例

```bash
curl -X POST http://127.0.0.1:7862/api/cnc-quick \
  -H "Content-Type: application/json" \
  -d '{"message": "304不锈钢零件 100x50x10mm 20个 钝化 报价多少钱"}'
```

响应：

```json
{
  "intent": "quote",
  "confidence": 0.9,
  "quote": {
    "material": "304不锈钢",
    "quantity": 20,
    "total_cost": 149.89,
    "total_price": 214.12,
    "unit_price": 21.41,
    "lead_time_days": 3
  },
  "latency_ms": 0
}
```

---

## 项目结构

```
CNC-AI-Brain-v12.0-Fusion/
├── app/                         # FastAPI 应用主目录
│   ├── main.py                  # 主入口 v12.0.0-fusion（工业融合）
│   ├── main_lite.py             # 精简模式（零外部依赖）
│   ├── cnc_quick.py             # CNC 快速通道（MTClaw FR 集成）
│   └── static/                  # 前端静态文件
│       ├── index_merged.html    # Web UI（Three.js 3D 预览）
│       └── three.min.js
├── src/                         # 核心业务模块
│   ├── ai_engine/               # AI 引擎（Ollama / OpenAI 兼容）
│   ├── core/                    # 核心组件
│   │   ├── model_registry.py    # 模型注册与自动发现
│   │   ├── model_auto_loader.py # 模型自动加载 + 按 vendor 路由
│   │   ├── environment_detector.py # 硬件环境探测（CPU/GPU + 多厂商 vendor 识别）
│   │   └── skill_auto_loader.py # Skill 自动发现
│   ├── neuro_core/              # 神经核心
│   │   ├── serial_expert.py     # 5 专家串行会议（CFO/BI/工艺/战略/CEO）
│   │   ├── conflict_check.py    # DFM 工艺冲突检测
│   │   ├── reasoning_chain.py   # 可解释推理链（SHA-256 审计）
│   │   └── schema_validator.py  # 参数 Schema 校验
│   ├── runtime/                 # 运行时
│   │   ├── cad_pipeline_tot.py  # TOT 三管道竞争生成
│   │   ├── step_generator_occ.py # OpenCascade STEP 生成
│   │   ├── step_generator_dual.py # 双引擎路由（OCC / trimesh）
│   │   ├── step_parser.py       # STEP 文件解析（bbox+体积级）
│   │   ├── feature_extractor.py # C1 DFM 特征实测（OCP 拓扑遍历孔/壁厚/圆角）
│   │   ├── part_analysis.py     # DFM 规则 + 三级取值链 + 工艺路线
│   │   ├── dfm_advisor.py       # C2 DFM 微调建议（结构化修改建议）
│   │   ├── tool_selector.py     # C3 刀具审核（钻头/丝锥/沉头刀选刀）
│   │   ├── quote_explainer.py   # C5 白盒说明（逐项费用拆解）
│   │   ├── quote_adapter.py     # 报价适配器（v3.0 Excel 公式还原）
│   │   ├── quote_xlsx_generator.py # XLSX 报价单生成
│   │   ├── export_bundler.py    # C6 ZIP 打包导出
│   │   ├── history_lookup.py    # 历史订单查询
│   │   ├── skill_caller.py      # Skill 调用器
│   │   ├── event_bus.py         # 事件总线
│   │   └── progress_reporter.py # 进度报告
│   ├── data/                    # 数据层
│   │   └── rag_engine.py        # RAG 检索引擎
│   └── safety/                  # 安全
│       └── audit_logger.py      # SHA-256 哈希链审计
├── config/                      # 配置文件
│   ├── version.txt              # 版本号（全局单一来源）
│   ├── models.json              # 模型配置（含 vendor 字段 + vendor_routing）
│   ├── tolerance.yaml           # 公差/粗糙度/工艺系数
│   ├── experts/                 # 5 专家角色 Prompt
│   └── skills/                  # Skill YAML 定义
├── data/                        # 运行时数据
│   ├── step/                    # 生成的 STEP/STL
│   ├── stl/                     # STL 预览
│   ├── uploads/                 # 用户上传
│   ├── exports/                 # ZIP 打包输出
│   ├── audit.db                 # 审计数据库
│   └── orders.db                # 订单数据库
├── .function-router/            # MTClaw FR 配置
│   ├── config.json              # FR 主配置
│   ├── cnc_functions.jsonl      # CNC 工具定义（OpenAI Function 格式）
│   └── scripts/                 # FR 工具执行脚本
├── Dockerfile                   # 参数化镜像（BASE_IMAGE / INSTALL_STEP）
├── docker-compose.yml           # 基础编排（各厂商公共）
├── docker-compose.cpu.yml       # 纯 CPU override
├── docker-compose.cuda.yml      # NVIDIA CUDA override
├── docker-compose.rocm.yml      # AMD ROCm override
├── .dockerignore                # Docker 构建忽略清单
├── requirements.txt             # Python 依赖（精简）
├── requirements-ocp.txt         # STEP 精确解析依赖（OCP/cadquery）
├── CNC_AI_Brain_启动.bat        # 一键启动脚本（Windows 本机）
├── MUSA_vLLM_启动.bat           # 摩尔线程 MUSA vLLM 启动（Windows）
└── scripts/                     # 部署脚本
    └── start_musa_vllm.sh       # 摩尔线程 MUSA vLLM 启动（Linux）
```

---

## 模型配置

系统支持自动发现并优雅降级。编辑 `config/models.json`：

```json
{
  "preference": "local",
  "cloud": [
    { "name": "mtclaw-fr", "api_url": "http://127.0.0.1:7863/v1", "quality_score": 101 }
  ],
  "local": [
    { "name": "qwen3-8b-gptq", "api_url": "http://127.0.0.1:32102/v1", "quality_score": 100 },
    { "name": "vllm-musa-qwen", "api_url": "http://127.0.0.1:8000/v1", "quality_score": 98 },
    { "name": "qwen3.6-35b-a3b", "api_url": "http://127.0.0.1:1234/v1", "quality_score": 92 }
  ]
}
```

**降级链**：`mtclaw-fr` (本地工具加速) → 云端 API → 本地 LLM → 规则引擎（离线永远可用）

---

## MTClaw Function Router 集成

### 工具定义

`cnc_functions.jsonl` 定义了两个 CNC 垂域工具：

| 工具 | 功能 | 响应时间 | Token 消耗 |
|------|------|----------|------------|
| `cnc_conflict_check` | 材料 × 工艺 × 表面处理冲突检测 | < 50ms | 0 |
| `cnc_quote_calc` | 材料费 + 加工费 + 表面处理费计算 | < 50ms | 0 |

### FR 配置要点

```json
{
  "listen_port": 7863,
  "tools_base_dir": "<CNC-AI-Brain 绝对路径>",
  "routing": { "base_url": "http://127.0.0.1:32102/v1", "model": "musachat_local" },
  "functions_file": "cnc_functions.jsonl",
  "scripts_dir": "scripts"
}
```

> 命中 CNC 工具 → 本地 Python 脚本执行（毫秒级，零 token 消耗）  
> 未命中 → 透明转发上游 LLM

---

## DFM 特征实测闭环（C1-C6）

上传 STEP 文件后，系统自动跑完 **C1→C6 六阶段流水线**，实现从"DFM 永远缺特征不评分"到"基于真实几何判定 + 白盒报价 + 一键打包"的完整闭环。

### 流水线总览

```
STEP 上传
  │
  ├─ C1 feature_extractor ──→ OCP 拓扑遍历：孔/壁厚/圆角/锥面/平面面积
  │   └─ rule_dfm 闭合 ──→ missing_fields: [] (之前 ['min_wall','hole_d','hole_depth'])
  │
  ├─ C2 dfm_advisor ───────→ DFM 微调建议（壁厚加厚/螺纹确认/沉头确认）
  │
  ├─ C3 tool_selector ─────→ 刀具清单（钻头/丝锥/沉头刀，换刀次数）
  │
  ├─ C4 calc_quote ────────→ 三路收敛报价（带 thread_count + surface_area_dm2）
  │
  ├─ C5 quote_explainer ───→ 白盒说明（材料费/加工费/螺纹费/利润逐项拆解）
  │
  └─ C6 create_bundle ─────→ ZIP 打包（10 个产物 JSON + STEP 原件）
```

### 各阶段详解

#### C1 特征实测（`src/runtime/feature_extractor.py`）

用 OpenCascade Python (OCP) 遍历 STEP B-rep 拓扑，只读提取几何特征：

| 特征 | 方法 | 输出 |
|------|------|------|
| 孔 | 圆柱面分类 + 轴向投影 | `holes[]`：d_mm / depth_mm / ld_ratio / through / thread_suspect |
| 最小壁厚 | 纯 numpy 点到三角面距离（内部采样） | `min_wall_mm`：{value, method, confidence} |
| 圆角 | Torus 过渡面 | `fillets`：{min_r_mm, torus_count} |
| 锥面 | Cone 面（沉头/倒角） | `stats.cone_face_count` |
| 平面面积 | BRepGProp 面积分 | `plane_area_dm2` |

**关键技术点**：
- `TopoDS.Face_s()` 向下转型：`TopExp_Explorer.Current()` 返回 `TopoDS_Shape` 基类，必须先转为 `TopoDS_Face` 才能 `BRepAdaptor_Surface(face)`
- 壁厚用纯 numpy 手写点到三角面距离（本环境 scipy 未安装，禁止 trimesh ProximityQuery）
- 容错：损坏/空/不存在文件 → 返回 `None`，绝不抛异常
- 性能：单件提取 < 2s

**DFM 闭合效果**：

| | C1 前 | C1 后 |
|---|---|---|
| `missing_fields` | `['min_wall','hole_d','hole_depth']` | `[]` |
| `dfm_score` | `None`（缺特征不评分） | 基于真实几何评分 |
| `data_source` | 全 `missing` | 全 `measured` |

#### C2 DFM 微调建议（`src/runtime/dfm_advisor.py`）

基于 C1 实测特征 + `rule_dfm` 判定结果，生成结构化修改建议：

```python
advise(features, dfm_result) -> {
    "suggestions": [
        {"id": "WALL-001", "severity": "error", "category": "壁厚",
         "title": "最小壁厚低于铝件下限", "action_type": "modify",
         "current_value": 1.086, "suggested_value": "≥1.5mm"},
        {"id": "THREAD-001", "severity": "warning", "category": "螺纹",
         "title": "36 个光圆柱孔疑为螺纹底孔", "action_type": "confirm"},
        # ...
    ],
    "summary": {"total": 5, "errors": 1, "warnings": 1, "infos": 3}
}
```

#### C3 刀具审核（`src/runtime/tool_selector.py`）

基于孔径分布自动选刀，识别螺纹底孔（Ø3.3→M4, Ø5.0→M6）和沉头孔（Ø11.0→M6 沉头）：

```python
select_tools(hole_summary, thread_suspect_count) -> {
    "tool_list": [
        {"tool_type": "钻头", "diameter_mm": 3.3, "hole_count": 8, "purpose": "M4 螺纹底孔"},
        {"tool_type": "丝锥", "diameter_mm": 4.0, "hole_count": 8, "purpose": "M4 螺纹"},
        {"tool_type": "沉头刀", "diameter_mm": 11.0, "hole_count": 10, "purpose": "M6 沉头孔"},
        # ...
    ],
    "summary": {"total_tool_types": 9, "drills": 6, "taps": 2, "countersinks": 1}
}
```

#### C4 最终报价（`app/main_lite.py: calc_quote`）

用 C1 实测特征驱动报价，螺纹孔附加费和表面面积计价自动计算：

```python
calc_quote(
    material="6061", quantity=10, weight_kg=1.273,
    max_dim_mm=450, surface_area_dm2=10.6868,
    tolerance="IT7", thread_count=36,
    dim_x=450, dim_y=115.18, dim_z=10
)
```

#### C5 白盒说明（`src/runtime/quote_explainer.py`）

逐项拆解报价明细，每项附公式与数值：

```
基础费:  15.0 元    | 固定基础费 = 15.0
材料费:  254.6 元   | weight_kg × mat_price = 1.273 × 200.0
加工费:  73.75 元   | (80 + 0.15 × 450) × 0.5
设置费:  1.5 元     | (30 / 10) × 0.5
质控费:  10.0 元    | 20 × 0.5
表面费:  0.0 元     | 0.0 + 0.0 × 10.6868
螺纹费:  180.0 元   | 36 × 5.0
利润:    1524.32 元 | 5081.07 × 0.3
────────────────────
最终价:  6605.4 元
```

#### C6 ZIP 打包（`src/runtime/export_bundler.py`）

`create_bundle()` 打包全部产物为 ZIP，输出到 `data/exports/`：

```
bundle_{part_id}_{timestamp}.zip
├── quote.json              # C4 报价结果
├── metadata.json           # 零件元数据
├── reasoning_chain.json    # C1-C6 推理链
├── dfm_advice.json         # C2 DFM 微调建议
├── tool_list.json          # C3 刀具清单
├── quote_explanation.json  # C5 白盒说明
├── process_route.json      # 工艺路线
├── dfm_result.json         # C1 DFM 判定
├── features.json           # C1 特征实测全量
└── {original}.step         # STEP 原件
```

### 编程式调用

```python
from src.runtime.feature_extractor import extract_features
from src.runtime.part_analysis import rule_dfm, draft_route
from src.runtime.dfm_advisor import advise
from src.runtime.tool_selector import select_tools
from src.runtime.quote_explainer import explain
from src.runtime.export_bundler import create_bundle
from app.main_lite import calc_quote

# C1 特征实测
features = extract_features("path/to/part.step")

# DFM 判定（闭合）
ctx = {"model_id": "part-001", "geometry": {"features": features, ...},
       "material": "6061", "quantity": 10, "tolerance": "IT7", "process": "三轴CNC"}
dfm = rule_dfm(ctx, {})

# C2 DFM 建议
advice = advise(features, dfm)

# C3 刀具审核
tools = select_tools(features["hole_summary"], 36)

# C4 报价
quote = calc_quote(material="6061", thread_count=36, surface_area_dm2=10.6868, ...)

# C5 白盒说明
explanation = explain(quote)

# C6 打包
create_bundle(task_id="part-001", files=[...], quote_data=quote, metadata={...})
```

### 测试

```bash
python -m pytest tests/test_feature_extractor.py tests/test_dfm_advisor.py \
  tests/test_tool_selector.py tests/test_quote_with_features.py \
  tests/test_quote_explainer.py tests/test_bundle_c2c6.py -v
# 60 passed in 16.51s
```

### 设计文档

详细设计见 [`docs/DFM特征实测feature_extractor详细设计.md`](docs/DFM特征实测feature_extractor详细设计.md)。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| **后端框架** | FastAPI + Uvicorn (ASGI) |
| **3D 引擎** | OpenCascade (OCP) / trimesh / numpy-stl |
| **CAD 格式** | STEP (ISO 10303) / STL / IGES |
| **B-rep 拓扑** | OCP TopExp_Explorer + BRepAdaptor_Surface（C1 特征实测） |
| **AI 模型** | Qwen3-8B GPTQ · Qwen2.5-7B · Qwen3.6-35B · GPT-OSS-120B · Step-3.7 Flash |
| **VLM** | MiniCPM-V-4.5（图纸视觉理解） |
| **OCR** | PaddleOCR |
| **数据库** | SQLite（审计 + 订单 + RAG） |
| **前端** | Three.js WebGL + 原生 JavaScript |
| **审计** | SHA-256 哈希链 |
| **工具加速** | MTClaw Function Router（OpenAI 兼容协议） |
| **模型推理** | vLLM MUSA / LMStudio / llama.cpp / Ollama |
| **硬件探测** | environment_detector（CPU/CUDA/ROCm/MUSA vendor 自动识别） + model_auto_loader 按 vendor 路由 |
| **容器化** | Docker Compose 多厂商 override（cpu/cuda/rocm） + requirements-ocp.txt |

---

## 贡献指南

本项目遵循 [CONTRIBUTING.md](CONTRIBUTING.md) 中定义的规范。要点：

- **Python 3.11** 目标，遵循 PEP 8
- 使用 `feat:` / `fix:` / `docs:` 等 Conventional Commits
- 禁止硬编码——所有端口、URL、系数从配置文件读取
- 提交 PR 前确保 `pytest tests/ -v` 全绿（含 C1-C6 特征实测闭环 60 测试）

### 开发环境

```bash
git clone https://github.com/timocao/CNC-AI-Brain.git
cd CNC-AI-Brain
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 7862
```

---

## 🔥 硬件厂商适配（已提供部署支持 vs 已实测）

> 如实区分「已提供部署支持」与「已实测通过」，避免虚标。完整说明见
> [`docs/HARDWARE_VENDORS.md`](docs/HARDWARE_VENDORS.md)。

### 已实测：摩尔线程 MUSA（当前生产后端）

当前**本地实测通过**的推理后端为 **摩尔线程 MUSA M1000**（vLLM MUSA），见 `config/models.json`
（端口 `32102` / `8000`）。系统在该后端上已跑通完整推理链路。

### 已提供部署支持 / 可用：四大厂商

| 厂商 | 部署入口 | 本地状态 |
|------|----------|----------|
| 摩尔线程 MUSA | `MUSA_vLLM_启动.bat` / `scripts/start_musa_vllm.sh` | ✅ 已实测 |
| NVIDIA CUDA | `docker-compose.yml` + `docker-compose.cuda.yml` | 🚧 已提供部署支持 |
| AMD ROCm | `docker-compose.yml` + `docker-compose.rocm.yml` | 🚧 已提供部署支持（未实测） |
| 纯 CPU | `docker-compose.yml` + `docker-compose.cpu.yml` | ✅ 可用（无 GPU） |

### AMD ROCm 部署命令

```bash
docker compose -f docker-compose.yml -f docker-compose.rocm.yml up -d --build
```

等价 `docker run`（含设备透传）：

```bash
docker run --device=/dev/kfd --device=/dev/dri --group-add video \
  -p 7862:7862 cnc-ai-brain:rocm
```

> `Dockerfile` 为参数化镜像（`BASE_IMAGE` / `INSTALL_STEP`）；ROCm override 使用基础镜像
> `rocm/pytorch:rocm6.4` 并透传 `/dev/kfd` + `/dev/dri`。AMD ROCm 目标硬件为
> RYZEN AI MAX+ 395 + Radeon 8060S 64GB 统一显存，本机无该硬件、尚未实测。

### 环境自动探测

`src/core/environment_detector.py` 自动识别厂商（CPU / CUDA / ROCm / MUSA），并按 vendor
将运行时切换到匹配推理后端；厂商探测与路由机制详见 [`docs/HARDWARE_VENDORS.md`](docs/HARDWARE_VENDORS.md)。

---

## 许可证

本项目基于 [MIT License](LICENSE) 开源。

---

## 👤 作者

| | |
|---|---|
| **timo.cao** | miscdd@163.com |
| **版本** | v12.0.0-fusion "工业融合" |
| **生成引擎** | 大帅教练系统 |

---

<p align="center">
  <sub>Made with ❤️ by timo.cao · CNC AI Brain Team · 2024–2026</sub>
</p>
