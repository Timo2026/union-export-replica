# env/ — 运行环境规格（conda）

> 节点不把 conda 环境本体入包（大、且机器相关）。这里给出**6 个环境的角色 + Python 版本 + 依赖清单位置**，
> 复刻者据此 `conda env create` 即可。

## 节点实测的 6 个 conda 环境

| 环境 | Python | 角色 |
|------|--------|------|
| `nemotron` | **3.12.14** | **推理**：vLLM + Nemotron（Omni/Embed/Qwen06），见 [`../models/MODELS.md`](../models/MODELS.md) |
| `occ` | 3.11.16 | **确定性内核/CAD**：Timo CNC 引擎、cadquery、trimesh、ezdxf（见 [`../engine/`](../engine/)） |
| `dfam` | 3.11.16 | DFM/材料/表面处理技能运行环境 |
| `lk-skills` | 3.11.16 | livekernel skill 运行环境 |
| `searxng` | 3.11.16 | 元搜索（可选，用于公开资料检索） |
| `vidproc` | 3.11.16 | 视频/多模态预处理（可选） |

> 注：`engine/environment.yml` 声明的环境名为 `step-render`（python 3.11，cadquery/cadquery-ocp/trimesh/cascadion/ezdxf/fastapi）。
> 节点上该 CAD/引擎依赖实际落在 `occ` 与 `dfam` 环境。复刻二选一：
> ```bash
> conda env create -f ../engine/environment.yml   # 声明式（name: step-render）
> ```
> 或直接在 `occ` 环境安装 `../engine/requirements.txt` + `requirements-ocp.txt`。

## 依赖清单位置（均在包内）

| 用途 | 清单 |
|------|------|
| 业务主干（livekernel） | [`../app/requirements.txt`](../app/requirements.txt) |
| 确定性内核（引擎） | [`../engine/requirements.txt`](../engine/requirements.txt) + [`../engine/requirements-ocp.txt`](../engine/requirements-ocp.txt) |
| CAD/几何（conda） | [`../engine/environment.yml`](../engine/environment.yml) |
| 推理（vLLM） | 在 `nemotron` 环境装 vLLM（对应 CUDA 13.0 的 NVFP4 构建），见 [`../models/fetch_and_launch.sh`](../models/fetch_and_launch.sh) |

> `app/requirements.txt`：PyYAML、fastapi、uvicorn、python-multipart、pypdf、openpyxl、pytest（可选：imap-tools、jsonschema）。
