"""创建 CNC-AI-Brain v12.0 Fusion 部署方案PPT"""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)

# ── Color Palette ──
DARK_BG = RGBColor(0x0D, 0x11, 0x1A)
ACCENT = RGBColor(0x63, 0x66, 0xF1)  # Indigo
ACCENT_GREEN = RGBColor(0x10, 0xB9, 0x81)
ACCENT_ORANGE = RGBColor(0xF5, 0x9E, 0x0B)
ACCENT_RED = RGBColor(0xEF, 0x44, 0x44)
ACCENT_BLUE = RGBColor(0x3B, 0x82, 0xF6)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GRAY = RGBColor(0x94, 0xA3, 0xB8)
LIGHT_GRAY = RGBColor(0x64, 0x74, 0x8B)
DARK_CARD = RGBColor(0x1E, 0x29, 0x3B)
DARK_CARD2 = RGBColor(0x15, 0x1E, 0x2D)

def set_slide_bg(slide, color):
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color

def add_rect(slide, left, top, width, height, fill_color, radius=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_color
    shape.line.fill.background()
    if radius:
        shape.adjustments[0] = radius
    return shape

def add_card(slide, left, top, width, height, title, body, accent_color=ACCENT):
    card = add_rect(slide, left, top, width, height, DARK_CARD, 0.05)
    # Accent bar
    bar = add_rect(slide, left, top, width, Inches(0.06), accent_color, 0)
    # Title
    txBox = slide.shapes.add_textbox(left + Inches(0.2), top + Inches(0.15), width - Inches(0.4), Inches(0.4))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(14)
    p.font.bold = True
    p.font.color.rgb = WHITE
    # Body
    txBox2 = slide.shapes.add_textbox(left + Inches(0.2), top + Inches(0.55), width - Inches(0.4), height - Inches(0.7))
    tf2 = txBox2.text_frame
    tf2.word_wrap = True
    p2 = tf2.paragraphs[0]
    p2.text = body
    p2.font.size = Pt(11)
    p2.font.color.rgb = GRAY
    return card

def add_title_bar(slide, title, subtitle=""):
    # Top bar
    bar = add_rect(slide, 0, 0, prs.slide_width, Inches(1.0), DARK_CARD2)
    txBox = slide.shapes.add_textbox(Inches(0.8), Inches(0.15), Inches(11), Inches(0.45))
    tf = txBox.text_frame
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(28)
    p.font.bold = True
    p.font.color.rgb = WHITE
    if subtitle:
        txBox2 = slide.shapes.add_textbox(Inches(0.8), Inches(0.58), Inches(11), Inches(0.3))
        tf2 = txBox2.text_frame
        p2 = tf2.paragraphs[0]
        p2.text = subtitle
        p2.font.size = Pt(13)
        p2.font.color.rgb = GRAY

def add_footer(slide, text="CNC-AI-Brain v12.0 Fusion · AMD + MTT 双节点部署方案"):
    txBox = slide.shapes.add_textbox(Inches(0.5), Inches(7.0), Inches(12), Inches(0.3))
    tf = txBox.text_frame
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(9)
    p.font.color.rgb = LIGHT_GRAY

# ════════════════════════════════════════════════
# Slide 1: 封面
# ════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
set_slide_bg(slide, DARK_BG)

# Big accent line
add_rect(slide, Inches(0.8), Inches(1.8), Inches(0.08), Inches(3.5), ACCENT)

txBox = slide.shapes.add_textbox(Inches(1.2), Inches(1.6), Inches(11), Inches(1.2))
tf = txBox.text_frame
p = tf.paragraphs[0]
p.text = "CNC-AI-Brain v12.0 Fusion"
p.font.size = Pt(42)
p.font.bold = True
p.font.color.rgb = WHITE

txBox2 = slide.shapes.add_textbox(Inches(1.2), Inches(2.8), Inches(11), Inches(0.6))
tf2 = txBox2.text_frame
p2 = tf2.paragraphs[0]
p2.text = "双节点异构部署方案：AMD推理 + MTT路由"
p2.font.size = Pt(22)
p2.font.color.rgb = ACCENT

txBox3 = slide.shapes.add_textbox(Inches(1.2), Inches(3.6), Inches(11), Inches(0.8))
tf3 = txBox3.text_frame
p3 = tf3.paragraphs[0]
p3.text = "AMD RYZEN AI MAX+ 395 (64GB VRAM)  ◇  摩尔线程 AIBOOK (arm64)"
p3.font.size = Pt(15)
p3.font.color.rgb = GRAY

txBox4 = slide.shapes.add_textbox(Inches(1.2), Inches(5.2), Inches(11), Inches(0.8))
tf4 = txBox4.text_frame
lines = ["架构：OpenClaw → MTClaw Function Router → CNC-AI-Brain (FastAPI + TOT)", "核心技术：TOT多管线竞争 · 双引擎STEP · 5专家决策会议 · 防篡改审计", "作者: timo.cao | 邮箱: miscdd@163.com | 生成: 数字生命卡兹克 + 大帅教练系统"]
for i, line in enumerate(lines):
    if i == 0:
        p4 = tf4.paragraphs[0]
    else:
        p4 = tf4.add_paragraph()
    p4.text = line
    p4.font.size = Pt(11)
    p4.font.color.rgb = LIGHT_GRAY

add_footer(slide)

# ════════════════════════════════════════════════
# Slide 2: 项目全景
# ════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, DARK_BG)
add_title_bar(slide, "项目全景：六大核心能力", "CNC-AI-Brain v12.0 Fusion — 从接单到报价的全链路AI自动化")
add_footer(slide)

cards = [
    ("🧠 TOT 3管线竞争", "LLM + Regex + 知识库并行推理\n打分陪审团自动选最优结果\n4维评分: Schema/覆盖/几何/包围盒", ACCENT),
    ("🎨 双引擎CAD生成", "OCC: B-Rep精确STEP → CAM直出刀路\ntrimesh: 三角网格 → 浏览器3D预览\n6种零件: 法兰/轴套/轴/平板/箱体/支架", ACCENT_GREEN),
    ("💰 即时报价引擎", "24种材料 × 14种表面处理\n精度/五轴/线切割附加费\n规则引擎精确计算 <1秒", ACCENT_ORANGE),
    ("🏛️ 5专家决策会议", "CFO(财务)→BI(历史)→工艺总监(冲突)→战略官→CEO(裁决)\nCFO一票否决权 + CEO可覆写\n哈希链SHA-256防篡改审计", ACCENT_RED),
    ("📄 多格式文件解析", "STEP/STL/PDF/DWG/DXF/XLSX/ZIP\nPaddleOCR + MiniCPM-V VLM图纸理解\n统一PartSpec输出", ACCENT_BLUE),
    ("🔄 模型自发现+降级", "12云厂商 + Ollama/LMStudio本地\nauto-detect → auto-fallback\ncloud → local → regex(离线保证)", RGBColor(0xA8, 0x55, 0xF7)),
]

for i, (title, body, color) in enumerate(cards):
    col = i % 3
    row = i // 3
    left = Inches(0.5 + col * 4.2)
    top = Inches(1.3 + row * 3.0)
    add_card(slide, left, top, Inches(3.9), Inches(2.7), title, body, color)

# ════════════════════════════════════════════════
# Slide 3: 硬件拓扑
# ════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, DARK_BG)
add_title_bar(slide, "硬件拓扑：双节点异构部署", "AMD RYZEN AI MAX+ 395 ⬌ MTT AIBOOK arm64")
add_footer(slide)

# Node A Card
card_a = add_rect(slide, Inches(0.5), Inches(1.3), Inches(5.8), Inches(5.3), DARK_CARD, 0.05)
add_rect(slide, Inches(0.5), Inches(1.3), Inches(5.8), Inches(0.06), ACCENT_BLUE)
txA = slide.shapes.add_textbox(Inches(0.8), Inches(1.5), Inches(5.2), Inches(0.4))
tA = txA.text_frame; pA = tA.paragraphs[0]
pA.text = "🔵 节点A · AMD 推理节点 (Windows x64)"
pA.font.size = Pt(16); pA.font.bold = True; pA.font.color.rgb = WHITE

specs_a = [
    "CPU: AMD RYZEN AI MAX+ 395 @ 3.00 GHz",
    "GPU: AMD Radeon 8060S / 64GB 统一显存",
    "RAM: 128 GB (可用 ~64GB)",
    "存储: ~400GB 可用",
    "",
    "▸ Ollama (ROCm加速) :11434",
    "▸ LMStudio (OpenAI兼容) :1234",
    "▸ CNC-AI-Brain FastAPI :7862",
    "▸ llama.cpp (备选) :1250",
    "",
    "主力推理: Qwen3.6-35B-A3B",
    "VLM: MiniCPM-V-4.5",
    "重型: GPT-OSS-120B (@60GB)",
]
txAs = slide.shapes.add_textbox(Inches(0.8), Inches(2.1), Inches(5.2), Inches(4.2))
tfAs = txAs.text_frame; tfAs.word_wrap = True
for i, line in enumerate(specs_a):
    p = tfAs.paragraphs[0] if i == 0 else tfAs.add_paragraph()
    p.text = line
    p.font.size = Pt(11)
    p.font.color.rgb = GRAY if not line.startswith("▸") else WHITE

# Node B Card
card_b = add_rect(slide, Inches(6.8), Inches(1.3), Inches(5.8), Inches(5.3), DARK_CARD, 0.05)
add_rect(slide, Inches(6.8), Inches(1.3), Inches(5.8), Inches(0.06), ACCENT_GREEN)
txB = slide.shapes.add_textbox(Inches(7.1), Inches(1.5), Inches(5.2), Inches(0.4))
tB = txB.text_frame; pB = tB.paragraphs[0]
pB.text = "🟢 节点B · MTT 路由节点 (Ubuntu arm64)"
pB.font.size = Pt(16); pB.font.bold = True; pB.font.color.rgb = WHITE

specs_b = [
    "CPU: 摩尔线程 arm64",
    "RAM: MTT AIBOOK 配置",
    "OS: Ubuntu 22.04 LTS",
    "角色: 轻量路由代理",
    "",
    "▸ OpenClaw Gateway (会话管理)",
    "▸ MTClaw Function Router :18790",
    "▸ Tool Scripts (CNC工具本地执行)",
    "▸ Session Bridge Plugin",
    "",
    "工具加速: cnc_conflict_check",
    "工具加速: cnc_quote_calc",
    "LLM请求: 透明代理→节点A",
]
txBs = slide.shapes.add_textbox(Inches(7.1), Inches(2.1), Inches(5.2), Inches(4.2))
tfBs = txBs.text_frame; tfBs.word_wrap = True
for i, line in enumerate(specs_b):
    p = tfBs.paragraphs[0] if i == 0 else tfBs.add_paragraph()
    p.text = line
    p.font.size = Pt(11)
    p.font.color.rgb = GRAY if not line.startswith("▸") else WHITE

# Arrow in center
arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(6.25), Inches(3.5), Inches(0.6), Inches(0.4))
arrow.fill.solid(); arrow.fill.fore_color.rgb = ACCENT
arrow.line.fill.background()

# ════════════════════════════════════════════════
# Slide 4: 三层架构
# ════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, DARK_BG)
add_title_bar(slide, "三层架构：OpenClaw → MTClaw → CNC-AI-Brain")
add_footer(slide)

layers = [
    ("Layer 0 · OpenClaw Gateway", "nodejs24, 会话管理+多Agent调度", ACCENT),
    ("Layer 1 · MTClaw Function Router", "python, 工具代理+LLM路由, :18790", ACCENT_GREEN),
    ("Layer 2 · CNC-AI-Brain v12.0", "FastAPI, TOT管线+CAD生成+报价, :7862", ACCENT_ORANGE),
    ("Layer 3 · LLM 推理引擎", "Ollama/LMStudio/llama.cpp, 本地+云端", ACCENT_RED),
]

for i, (title, desc, color) in enumerate(layers):
    top = Inches(1.4 + i * 1.5)
    card = add_rect(slide, Inches(1.5), top, Inches(10.3), Inches(1.2), DARK_CARD, 0.05)
    add_rect(slide, Inches(1.5), top, Inches(0.08), Inches(1.2), color)
    
    txBox = slide.shapes.add_textbox(Inches(2.0), top + Inches(0.15), Inches(9.5), Inches(0.4))
    tf = txBox.text_frame
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(18); p.font.bold = True; p.font.color.rgb = WHITE
    
    txBox2 = slide.shapes.add_textbox(Inches(2.0), top + Inches(0.6), Inches(9.5), Inches(0.4))
    tf2 = txBox2.text_frame
    p2 = tf2.paragraphs[0]
    p2.text = desc
    p2.font.size = Pt(12); p2.font.color.rgb = GRAY

    if i < 3:
        arrow = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, Inches(6.2), top + Inches(1.15), Inches(0.3), Inches(0.3))
        arrow.fill.solid(); arrow.fill.fore_color.rgb = color
        arrow.line.fill.background()

# Data flow on right
flow_box = slide.shapes.add_textbox(Inches(1.5), Inches(7.0), Inches(10.3), Inches(0.3))
flow_tf = flow_box.text_frame
flow_p = flow_tf.paragraphs[0]
flow_p.text = "数据流: 用户请求 → OpenClaw(会话路由) → MTClaw(工具匹配/LLM路由) → CNC-AI-Brain(TOT推理) → LLM引擎"
flow_p.font.size = Pt(10); flow_p.font.color.rgb = LIGHT_GRAY; flow_p.alignment = PP_ALIGN.CENTER

# ════════════════════════════════════════════════
# Slide 5: 权重分配
# ════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, DARK_BG)
add_title_bar(slide, "推理权重分配：AMD GPU 64GB 统一显存", "4模型 + KV Cache 布局 · 降级链策略")
add_footer(slide)

models = [
    ("Qwen3.6-35B-A3B", "~20GB", "主力推理 (中文MoE)", "⭐⭐⭐", ACCENT, 0.42),
    ("MiniMax-M2.7", "~15GB", "辅助推理 (轻量)", "⭐⭐", ACCENT_GREEN, 0.32),
    ("MiniCPM-V-4.5", "~8GB", "VLM图纸理解", "⭐⭐", ACCENT_BLUE, 0.18),
    ("KV Cache + 系统", "~21GB", "推理缓存", "—", GRAY, 0.08),
]

for i, (name, size, desc, stars, color, ratio) in enumerate(models):
    top = Inches(1.5 + i * 1.35)
    
    # Label
    txBox = slide.shapes.add_textbox(Inches(0.8), top, Inches(2.8), Inches(0.4))
    tf = txBox.text_frame
    p = tf.paragraphs[0]
    p.text = f"{stars}  {name}"
    p.font.size = Pt(14); p.font.bold = True; p.font.color.rgb = WHITE
    
    # Description
    txBox2 = slide.shapes.add_textbox(Inches(0.8), top + Inches(0.35), Inches(4.0), Inches(0.35))
    tf2 = txBox2.text_frame
    p2 = tf2.paragraphs[0]
    p2.text = desc
    p2.font.size = Pt(10); p2.font.color.rgb = GRAY
    
    # Size
    txBox3 = slide.shapes.add_textbox(Inches(3.5), top + Inches(0.1), Inches(2.0), Inches(0.35))
    tf3 = txBox3.text_frame
    p3 = tf3.paragraphs[0]
    p3.text = size
    p3.font.size = Pt(13); p3.font.bold = True; p3.font.color.rgb = color

# Bar chart area
for i, (name, size, desc, stars, color, ratio) in enumerate(models):
    bar_top = Inches(1.5 + i * 1.35)
    bar_width = ratio * Inches(7.0)
    bar = add_rect(slide, Inches(5.5), bar_top + Inches(0.1), bar_width, Inches(0.8), color, 0.06)

# Total bar
add_rect(slide, Inches(5.5), Inches(1.5 + 4 * 1.35), Inches(7.0), Inches(0.06), GRAY)

# GPT-OSS-120B note
txNote = slide.shapes.add_textbox(Inches(5.5), Inches(1.5 + 4 * 1.35 + 0.2), Inches(7.0), Inches(0.8))
tfn = txNote.text_frame; tfn.word_wrap = True
pn = tfn.paragraphs[0]
pn.text = "💡 重型模式: GPT-OSS-120B-MXFP4 可独占 ~60GB，替换常规模式全部模型"  ; pn.font.size = Pt(11); pn.font.color.rgb = ACCENT_ORANGE

# Right side: Fallback chain
fc_box = add_rect(slide, Inches(8.5), Inches(6.0), Inches(4.3), Inches(1.2), DARK_CARD2, 0.05)
txFC = slide.shapes.add_textbox(Inches(8.7), Inches(6.1), Inches(3.9), Inches(1.0))
tfc = txFC.text_frame; tfc.word_wrap = True
pfc = tfc.paragraphs[0]
pfc.text = "降级链: Qwen35B → MiniMax-2.7 → DeepSeek云端 → Regex(离线)"
pfc.font.size = Pt(10); pfc.font.color.rgb = WHITE
pfc2 = tfc.add_paragraph()
pfc2.text = "切换时间: 热加载 <10s | 冷加载 ~30s"
pfc2.font.size = Pt(10); pfc2.font.color.rgb = GRAY

# ════════════════════════════════════════════════
# Slide 6: MTClaw 路由
# ════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, DARK_BG)
add_title_bar(slide, "MTClaw Function Router：工具加速 + LLM路由", "CNC垂域工具毫秒级本地响应 · LLM请求透明代理到AMD节点")
add_footer(slide)

# Left: Flow diagram
add_card(slide, Inches(0.5), Inches(1.3), Inches(5.8), Inches(2.8),
         "请求路由决策流程",
         "① 用户请求到达 MTClaw Router :18790\n② 路由模型 (qwen3.6-35b-a3b) 判断意图\n③ CNC工具? → 本地tool脚本执行 (<50ms)\n④ 通用LLM? → 透明代理到AMD节点\n⑤ 返回结果（含推理链+置信度）", ACCENT)

add_card(slide, Inches(0.5), Inches(4.4), Inches(5.8), Inches(2.5),
         "已注册CNC垂域工具",
         "🔧 cnc_conflict_check — 工艺冲突检测\n   材料×表面处理×公差 禁忌组合验证\n💰 cnc_quote_calc — 智能报价计算\n   材料费+加工费+表面处理+总成本+交期\n⚡ 本地执行: <50ms | 规则引擎精度100%", ACCENT_GREEN)

# Right: config details
add_card(slide, Inches(6.8), Inches(1.3), Inches(5.8), Inches(5.6),
         "MTClaw config.json 关键配置",
         "Routing Model (路由层):\n  base_url: http://<AMD_IP>:11434/v1\n  model: qwen3.6-35b-a3b\n\nUpstream Model (上游层):\n  base_url: http://<AMD_IP>:1234/v1\n  model: qwen/qwen3.6-35b-a3b\n\nTool层 (本地脚本):\n  tools_base_dir: ~/contestant/my-agent\n  timeout: 30s\n  max_rounds: 6\n\nOpenClaw接入:\n  baseUrl: http://127.0.0.1:18790/v1\n  provider: function_router", ACCENT_BLUE)

# ════════════════════════════════════════════════
# Slide 7: 部署流程
# ════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, DARK_BG)
add_title_bar(slide, "部署流程：双节点一键就绪", "节点A (AMD Windows) + 节点B (MTT Ubuntu) 并行部署")
add_footer(slide)

# Step timeline
steps = [
    ("1", "安装Node.js24", "nvm install 24", ACCENT),
    ("2", "安装OpenClaw", "curl ... openclaw.ai/install.sh", ACCENT_GREEN),
    ("3", "安装MTClaw", "pip install . + config.json", ACCENT_ORANGE),
    ("4", "部署Tool脚本", "functions.jsonl + .sh", ACCENT_RED),
    ("5", "安装Ollama", "ollama pull qwen3.6-35b", ACCENT_BLUE),
    ("6", "安装Python依赖", "pip install -r requirements.txt", RGBColor(0xA8, 0x55, 0xF7)),
    ("7", "配置跨节点连接", "config/models.json mtclaw-fr", ACCENT),
    ("8", "全栈启动+验证", "一键启动.bat + health check", ACCENT_GREEN),
]

for i, (num, title, desc, color) in enumerate(steps):
    col = i % 4
    row = i // 4
    left = Inches(0.5 + col * 3.2)
    top = Inches(1.4 + row * 2.8)
    
    # Step number
    circle = slide.shapes.add_shape(MSO_SHAPE.OVAL, left + Inches(0.2), top, Inches(0.6), Inches(0.6))
    circle.fill.solid(); circle.fill.fore_color.rgb = color
    circle.line.fill.background()
    tf_c = circle.text_frame; tf_c.word_wrap = False
    p_c = tf_c.paragraphs[0]
    p_c.text = num; p_c.font.size = Pt(20); p_c.font.bold = True
    p_c.font.color.rgb = WHITE; p_c.alignment = PP_ALIGN.CENTER
    
    txT = slide.shapes.add_textbox(left + Inches(1.0), top, Inches(2.0), Inches(0.3))
    p_t = txT.text_frame.paragraphs[0]
    p_t.text = title; p_t.font.size = Pt(13); p_t.font.bold = True; p_t.font.color.rgb = WHITE
    
    txD = slide.shapes.add_textbox(left, top + Inches(0.8), Inches(3.0), Inches(0.35))
    p_d = txD.text_frame.paragraphs[0]
    p_d.text = desc; p_d.font.size = Pt(10); p_d.font.color.rgb = GRAY
    
    # Connecting line
    if col < 3:
        line = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, left + Inches(3.0), top + Inches(0.2), Inches(0.3), Inches(0.2))
        line.fill.solid(); line.fill.fore_color.rgb = GRAY; line.line.fill.background()

# Docker alternative
docker_box = add_rect(slide, Inches(0.5), Inches(6.7), Inches(12.3), Inches(0.6), DARK_CARD2)
txDocker = slide.shapes.add_textbox(Inches(0.8), Inches(6.72), Inches(11.7), Inches(0.5))
tfD = txDocker.text_frame
pD = tfD.paragraphs[0]
pD.text = "🐳 备选: Docker Compose (含Ollama+qwen2.5:3b+CNC-AI-Brain) — docker compose up -d → http://localhost:7861"
pD.font.size = Pt(10); pD.font.color.rgb = GRAY; pD.alignment = PP_ALIGN.CENTER

# ════════════════════════════════════════════════
# Slide 8: 演示场景
# ════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, DARK_BG)
add_title_bar(slide, "演示场景：CNC工厂接单全链路", "从询价到决策的全自动化演示")
add_footer(slide)

scenes = [
    ("场景1 · 快速报价", ACCENT,
     "用户: \"6061铝合金法兰 100件 阳极氧化 报价\"\n\n系统响应:\n  • TOT 3管线并行提取参数\n  • 规则引擎精确计算成本\n  • 材料费+加工费+表面处理+总价\n  • 响应时间: <1秒"),
    ("场景2 · 工艺冲突自动拦截", ACCENT_RED,
     "用户: \"304不锈钢轴套 200个 阳极氧化\"\n\n系统响应:\n  • 冲突检测: 304+阳极氧化=不可能!\n  • 直接阻断报价，给出修正建议\n  • 建议: 304不锈钢请改用钝化处理\n  • 避免了一次5万元质量事故"),
    ("场景3 · 5专家会议决策", ACCENT_ORANGE,
     "用户: \"钛合金TC4叶轮 20件 IT5精度 能接吗\"\n\n系统响应:\n  • CFO: 成本¥10.3万，利润31%\n  • BI: 客户复购3次，付款准时\n  • 工艺: IT6可做，IT5需五轴\n  • CEO: 批准接单 (80秒完成)"),
    ("场景4 · STEP图纸上传+3D预览", ACCENT_GREEN,
     "用户: 上传法兰STEP文件\n\n系统响应:\n  • OpenCascade解析B-Rep几何\n  • 生成精确STEP + trimesh STL\n  • Three.js浏览器3D交互预览\n  • 一键报价 + 一键导出ZIP包"),
]

for i, (title, color, body) in enumerate(scenes):
    col = i % 2
    row = i // 2
    left = Inches(0.5 + col * 6.4)
    top = Inches(1.3 + row * 3.0)
    add_card(slide, left, top, Inches(6.1), Inches(2.7), title, body, color)

# ════════════════════════════════════════════════
# Slide 9: 性能基准
# ════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, DARK_BG)
add_title_bar(slide, "性能基准 & 竞品对比")
add_footer(slide)

# Performance table
table_data = [
    ("场景", "响应时间", "精度", "瓶颈"),
    ("CNC工具调用", "<50ms", "100%", "本地脚本"),
    ("简单报价", "<1s", "规则引擎", "计算"),
    ("TOT 3管线竞争", "3-8s", ">95%", "LLM推理"),
    ("5专家完整会议", "15-30s", ">90%", "串行LLM×5"),
    ("STEP生成 (6种零件)", "0.5-2s", "B-Rep精确", "OCC"),
    ("VLM图纸理解", "3-5s", ">85%", "VLM推理"),
    ("3D预览加载", "<1s", "—", "Three.js"),
]

add_rect(slide, Inches(0.5), Inches(1.3), Inches(6.0), Inches(5.3), DARK_CARD, 0.05)
for i, (c1, c2, c3, c4) in enumerate(table_data):
    y = Inches(1.5 + i * 0.6)
    is_header = i == 0
    colors = [WHITE if is_header else GRAY for _ in range(4)]
    sizes = [Pt(12) if is_header else Pt(10) for _ in range(4)]
    bolds = [True, True, True, True] if is_header else [False, False, False, False]
    
    for j, (text, x_offset) in enumerate([(c1, 0.8), (c2, 2.3), (c3, 3.8), (c4, 5.0)]):
        tx = slide.shapes.add_textbox(Inches(x_offset), y, Inches(1.5), Inches(0.35))
        p = tx.text_frame.paragraphs[0]
        p.text = text
        p.font.size = sizes[j]; p.font.bold = bolds[j]; p.font.color.rgb = colors[j]
    
    if is_header:
        add_rect(slide, Inches(0.5), Inches(1.5 + 0.6), Inches(6.0), Inches(0.01), GRAY)

# Right: Comparison
add_card(slide, Inches(7.0), Inches(1.3), Inches(5.8), Inches(2.5),
         "人工 vs Union·由你",
         "               人工         Union·由你\n报价耗时    30min-2h         <1s\n决策耗时    2h-2天          ~80s\n错误率      ~5%               0%(硬规则)\n工艺漏检     依赖经验        100%覆盖\n可审计        无               哈希链\n7×24         ❌                ✅", ACCENT_GREEN)

add_card(slide, Inches(7.0), Inches(4.1), Inches(5.8), Inches(2.5),
         "Union·由你 vs 通用LLM系统",
         "                通用LLM       Union·由你\n报价方式      LLM估算          规则引擎精确\n决策方式      单模型           5专家串行\n审计            无               哈希链防篡改\n离线能力      部分             100%离线\n自适应        手动配置         零配置启动\n部署           源码             源码+Docker+EXE", ACCENT)

# ════════════════════════════════════════════════
# Slide 10: 总结
# ════════════════════════════════════════════════
slide = prs.slides.add_slide(prs.slide_layouts[6])
set_slide_bg(slide, DARK_BG)
add_footer(slide)

add_rect(slide, Inches(0.8), Inches(1.8), Inches(0.08), Inches(3.5), ACCENT)

txBox = slide.shapes.add_textbox(Inches(1.2), Inches(1.6), Inches(11), Inches(1.0))
tf = txBox.text_frame
p = tf.paragraphs[0]
p.text = "部署方案总结"
p.font.size = Pt(36); p.font.bold = True; p.font.color.rgb = WHITE

highlights = [
    ("✅ 算力最大化", "AMD 64GB统一显存加载4模型，按复杂度自动切换"),
    ("✅ 工具加速", "MTClaw CNC垂域工具ms级本地响应，降低LLM调用次数"),
    ("✅ 智能降级", "OCC→trimesh、本地LLM→云端、TOT→单管线，零中断"),
    ("✅ 双节点解耦", "MTT路由(轻量) + AMD推理(重载)，互不干扰"),
    ("✅ 生产就绪", "审计链+SHA-256+Shadow模式，满足工业合规"),
]

for i, (title, desc) in enumerate(highlights):
    top = Inches(2.8 + i * 0.85)
    txB = slide.shapes.add_textbox(Inches(1.2), top, Inches(4.0), Inches(0.35))
    pB = txB.text_frame.paragraphs[0]
    pB.text = title
    pB.font.size = Pt(16); pB.font.bold = True; pB.font.color.rgb = ACCENT_GREEN
    
    txD = slide.shapes.add_textbox(Inches(5.0), top, Inches(7.5), Inches(0.35))
    pD = txD.text_frame.paragraphs[0]
    pD.text = desc
    pD.font.size = Pt(13); pD.font.color.rgb = GRAY

txBox2 = slide.shapes.add_textbox(Inches(1.2), Inches(6.5), Inches(11), Inches(0.6))
tf2 = txBox2.text_frame
p2 = tf2.paragraphs[0]
p2.text = "提交: 2026-08-08 · 比赛项目 · AMD + MTT双节点方案 · timo.cao"
p2.font.size = Pt(11); p2.font.color.rgb = LIGHT_GRAY

# Save
output_path = r"C:\Users\<user>\Desktop\比赛\摩尔\新建文件夹\AMD\CNC-AI-Brain-v12.0-Fusion\Timo_CNC-AI-Brain-v12.0-Fusion\CNC-AI-Brain_v12_部署方案.pptx"
prs.save(output_path)
print(f"PPT saved to: {output_path}")
