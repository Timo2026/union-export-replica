---
name: superhero
description: "Generate a 1024x1024 superhero-style portrait from a face photo. Use when: user asks 帮我生成超级英雄照片, 超级英雄, 超人, 变装, superhero photo, or sends a face photo asking for a hero look."
metadata: { "openclaw": { "emoji": "🦸", "requires": { "bins": ["python3", "bash"] } } }
---

# Superhero Photo Generator

用户发一张正面人脸照片，本地 ComfyUI（FLUX + PuLID）生成超级英雄风格肖像。

## Run

**最简单的调用方式（推荐）** —— helper 会自动从 OpenClaw 的 inbound 目录拿用户最新上传的图：

```bash
"/home/Developer/.openclaw/skills/superhero/run_helper.sh"
```

**显式传图路径**（仅当用户已经提供了 disk 上的具体路径时再用）：

```bash
"/home/Developer/.openclaw/skills/superhero/run_helper.sh" "<absolute_face_image_path>"
```

**后端配置**（环境变量，均有默认值）：

- `COMFYUI_URL` — ComfyUI HTTP 地址，默认 `http://127.0.0.1:8200`
- `COMFYUI_OUTPUT` — ComfyUI 输出目录，默认 `$WORKSHOP_DIR/comfyui-app/ComfyUI/output`
- `COMFYUI_VENV` — 带 `requests` 依赖的 Python venv 路径；不设则依次尝试 workshop bundle 布局和系统 python3
- `WORKSHOP_DIR` / `OPENCLAW_HOME` — 默认由脚本位置自动推导，一般无需设置

**绝对不要做的事**:

- 不要用 `find` 在系统里搜其他叫 `superhero_helper.py` 的文件来代替——别的 demo 残留路径不一样，跑了会污染状态。
- 不要把 skill 路径改写成 `~/.openclaw`、`/tmp/...` 或任何硬编码路径——用上面给出的绝对路径。
- 不要瞎编 `/tmp/input_image.png` 之类的路径——helper 找不到文件会自动回退到 inbound 目录，所以**直接无参调用**就够了。

## Output

helper 在 stdout 的最后一行打印：

```
MEDIA:<absolute_path_to_png>
```

把 **这一整行**（包括 `MEDIA:` 前缀和绝对路径）原封不动复制到你的回复里：

```
你的超级英雄照片来啦！
MEDIA:<helper 真正打印的那条路径>
```

OpenClaw Web UI 看到 `MEDIA:` 行会自动把 PNG 渲染成内联图片。

## Rules

- 直接执行，不要先说"正在生成"。
- 命令失败时只回复"生成失败，请稍后重试"。
- 不要展示 `OK`、文件路径、stderr 等中间输出，只保留 `MEDIA:` 行 + 一句话寒暄。
- 单次约 1 分钟，不要重复触发。
