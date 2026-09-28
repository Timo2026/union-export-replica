# Union·由你 CNC AI 工艺大脑 — 使用说明书

> 版本: v12.0.0-fusion | 更新:A-2026-09-06 | 作者: timo.cao

## 目录

1. [环境准备](#1-环境准备)
2. [启动服务](#2-启动服务)
3. [Web 界面使用](#3-web-界面使用)
4. [API 接口](#4-api-接口)
5. [STEP 上传与 3D 预览](#5-step-上传与-3d-预览)
6. [报价计算说明](#6-报价计算说明)
7. [故障排查](#7-故障排查)

---

## 1. 环境准备

### 方式 A: conda 环境（推荐，支持 STEP 精确解析）

```bash
# 创建环境（含 OCP + cadquery + trimesh + cascadion）
conda env create -f environment.yml
conda activate step-render
```

### 方式 B: venv 虚拟环境（精简，仅规则引擎报价）

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux
set PYTHONUTF8=1              # Windows 避免 GBK 编码问题
pip install -r requirements.txt
```

### 方式 C: Docker

```bash
cp .env.example .env          # 填入 API Key
docker-compose up -d
```

---

## 2. 启动服务

### Windows 一键启动

```bash
CNC_AI_Brain_启动.bat         # 自动检测 conda step-render 环境
```

### 手动启动

```bash
conda activate step-render
python -m uvicorn app.main:app --host 127.0.0.1 --port 7862
```

### 精简模式（零依赖）

```bash
python app/main_lite.py
```

启动后浏览器访问 **http://127.0.0.1:7862**

---

## 3. Web 界面使用

| 功能 | 操作 |
|------|------|
| 一句话报价 | 输入 "304不锈钢 100×50×10mm 20个 报价" → 回车 |
| 上传图纸 | 拖拽 STEP/STL/DXF/PDF 到上传区 |
| 3D 预览 | 上传 STEP 后自动渲染 Three.js 预览 |
| 打包下载 | 点击 "📦 打包下载ZIP" 获取 STEP+STL+XLSX |

---

## 4. API 接口

### 健康检查

```bash
curl http://127.0.0.1:7862/api/health
```

### 快速报价（自然语言）

```bash
curl -X POST http://127.0.0.1:7862/api/cnc-quick \
  -H "Content-Type: application/json" \
  -d '{"message": "6061铝合金 100x50x10mm 30个 阳极氧化 报价"}'
```

响应：
```json
{
  "intent": "quote",
  "quote": {
    "material": "6061",
    "quantity": 30,
    "weight_kg": 0.405,
    "material_cost": 1234.56,
    "machining_cost": 450.00,
    "surface_cost": 80.00,
    "total_price": 1764.56,
    "final_price": 2293.93,
    "lead_time_days": 5
  }
}
```

### 上传 STEP 文件

```bash
curl -X POST http://127.0.0.1:7862/api/upload \
  -F "file=@零件.step" \
  -F "material=6061" \
  -F "quantity=10" \
  -F "surface=阳极氧化"
```

### 完整端点列表

访问 **http://127.0.0.1:7862/docs** (Swagger UI)

---

## 5. STEP 上传与 3D 预览

### 支持格式

| 格式 | 扩展名 | 解析引擎 |
|------|--------|----------|
| STEP | .step .stp | cadquery + cascadion (OCC) → trimesh |
| STL | .stl | trimesh 直接 |
| DXF | .dxf | ezdxf |
| PDF | .pdf | pdfplumber (可选) |
| Excel | .xlsx | openpyxl |

### 单位处理

STEP 文件标准单位为毫米（mm）。系统使用 **cadquery.importStep 作为权威尺寸源**，自动检测并修正 cascadion 的米制输出（×1000 转毫米）。

### 3D 预览

上传 STEP 后，系统自动：
1. cadquery 解析真实尺寸 + 体积
2. trimesh 导出 STL（单位修正后）
3. Three.js WebGL 渲染预览
4. 返回 `stl_url` 供前端加载

---

## 6. 报价计算说明

### 价格公式（白盒）

```
基础费 base = 15 + 60 × weight_kg × (mat_price / 22)
单价 unit = base × 工艺系数 × 公差系数 × 粗糙系数 + 表面处理费 + 螺纹费
总价 total = unit × quantity × 批量折扣
最终价 final = total × (1 + 利润率)
```

### 费用三栏分解

| 费用项 | 公式 |
|--------|------|
| 材料费 | `60 × weight_kg × (mat_price/22) × 工艺×公差×粗糙 × 数量 × 折扣` |
| 加工费 | `15 × 工艺×公差×粗糙 × 数量 × 折扣 + 螺纹费` |
| 表面费 | `(表面固定费 + 表面面积费率 × 面积dm²) × 数量 × 折扣` |

### 批量折扣

| 数量 | 折扣 |
|------|------|
| ≥100 件 | ×0.7 |
| ≥50 件 | ×0.8 |
| ≥20 件 | ×0.9 |
| <20 件 | ×1.0 |

### 支持8种材料

45钢 / Q235 / 6061 / 7075 / 304 / 316L / TC4 / 黄铜（含别名归一）

### 支持9种表面处理

无 / 发黑 / 阳极氧化 / 镀锌 / 镀铬 / 镀镍 / 磷化 / 喷漆 / 喷砂

---

## 7. 故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| STEP 上传 400 | cascadion 未装 | `pip install cascadion` |
| 尺寸过小 (1.13mm) | 米制未转 | 确认 cadquery 可用 |
| 费用全 ¥0 | 旧版本 | 更新到 v12.0.0-fusion |
| 交期 "- 天" | 字段名不匹配 | 更新到 v12.0.0-fusion |
| pip GBK 错误 | Windows 编码 | `set PYTHONUTF8=1` |
| 端口占用 | 7862 被占 | `netstat -ano | findstr 7862` |
| 模型不可用 | 无本地 LLM | 自动降级规则引擎（正常） |

---

## 技术支持

- 邮箱: miscdd@163.com
- Issues: [GitHub Issues](../../issues)