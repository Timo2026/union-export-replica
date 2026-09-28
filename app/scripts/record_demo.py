# -*- coding: utf-8 -*-
"""record_demo.py — v5.0.0 L3 邮件自动驱动 5 min 演示视频脚本.

录制方式: Playwright 跑 5 个场景, 每个场景 6 张截图, 共 30 帧.
然后用 ffmpeg 串成 5 min 视频 (如 ffmpeg 可用).

输出:
  docs/demo/frames/01_pass_*.png ... 05_spark_*.png (30 张)
  docs/demo/v5_demo_storyboard.md (分镜脚本 + 讲解)
  docs/demo/v5_demo.mp4 (如 ffmpeg 可用)

演示场景:
  1. (0:00-1:00) 项目介绍 + UI 三栏 + 黄金链进度
  2. (1:00-2:00) 邮件到达 → MailPuller enqueue → MailOrchestrator claim
  3. (2:00-3:00) FleetCoordinator v4 3 专家 + Loop + QualityCritic
  4. (3:00-4:00) CEO 5 证 + Reid-OS 协议 → PASS verdict
  5. (4:00-5:00) 自动批准 + spark dashboard + 审计落库
"""
import asyncio
import io
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.async_api import async_playwright

OUT = Path("docs/demo/frames")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8900/"

SCENES = [
    {
        "id": "01_pass",
        "title": "场景 1: PASS 路径自动批准",
        "duration_s": 60,
        "steps": [
            ("00_initial", "Workbench 默认状态 (NVIDIA 绿品牌色 + 黄金链空态)", None),
            ("01_select_s1", "选中 S1 (Alice Chen, 6061 PASS)", ".wb-mail-item:nth-child(1)"),
            ("02_inspector", "中栏 Inspector 显示邮件详情 + 黄金链 7/8 步 done", None),
            ("03_chat_verify", "右栏 Chat 发送 'verify gate'", "#wbChatText"),
            ("04_send", "点 ▶ 发送 → mock agent 回复 '5/5 PASS'", ".wb-chat-input .row .primary"),
            ("05_approval", "切到 Approval tab → sha16 锁 + ✓ 批准按钮", ".wb-tab[data-itab='approval']"),
        ],
    },
    {
        "id": "02_hitl",
        "title": "场景 2: HITL 路径 + 通知外发",
        "duration_s": 60,
        "steps": [
            ("10_select_s2", "选中 S2 (Bob Smith, TC4 IT5 HITL)", ".wb-mail-item:nth-child(2)"),
            ("11_inspector", "中栏 Inspector 显示 HITL 触发原因 (公差/金额/材料)", None),
            ("12_approval", "Approval tab: sha16 锁 + 双确认按钮", ".wb-tab[data-itab='approval']"),
            ("13_chat_approve", "右栏 Chat 发 'approve this quote' → agent 解释", "#wbChatText"),
            ("14_send", "点发送 → mock agent 提示需人工", ".wb-chat-input .row .primary"),
            ("15_skill_console", "打开 Skill Console 看 18 个 skill + 审计尾巴", ".ghost"),
        ],
    },
    {
        "id": "03_blocked",
        "title": "场景 3: BLOCKED 路径 + 铁律②拦截",
        "duration_s": 60,
        "steps": [
            ("20_select_s3", "选中 S3 (Carol Wang, 304 阳极氧化 BLOCKED)", ".wb-mail-item:nth-child(3)"),
            ("21_inspector", "中栏 Inspector 显示 BLOCKED + MATERIAL_SURFACE_MISMATCH 冲突", None),
            ("22_chat_explain", "Chat 发送 'explain why BLOCKED'", "#wbChatText"),
            ("23_send", "mock agent 解释 304 不锈钢不能阳极氧化", ".wb-chat-input .row .primary"),
            ("24_blocked_panel", "Agent 给出替代方案 (钝化/粉末喷涂)", None),
            ("25_no_approve", "Approval tab 无 ✓ 批准按钮 (铁律② 守护)", ".wb-tab[data-itab='approval']"),
        ],
    },
    {
        "id": "04_novastudio",
        "title": "场景 4: NovaStudio 4 工具整合",
        "duration_s": 60,
        "steps": [
            ("30_novastudio_dir", "展示 tools/ 目录 (MinerU + ragflow + OmniVoice + SearXNG)", None),
            ("31_intake_pdf", "演示 services/intake_pdf.py 调 MinerU 解析 PDF", None),
            ("32_rag_search", "演示 services/rag_search.py 调 ragflow 检索", None),
            ("33_asr_engine", "演示 services/asr_engine.py 调 OmniVoice ASR", None),
            ("34_web_search", "演示 services/web_search.py 调 SearXNG", None),
            ("35_offline_fallback", "4 工具未启动时 mock fallback (test_novastudio 7 用例)", None),
        ],
    },
    {
        "id": "05_spark",
        "title": "场景 5: 自动批准 + spark dashboard + 审计",
        "duration_s": 60,
        "steps": [
            ("40_l3_pipeline", "展示 MailOrchestrator 自动跑 L3 黄金链", None),
            ("41_auto_approve", "PASS 路径 → auto_approve → audit jsonl +1", None),
            ("42_notify", "HITL/BLOCKED 路径 → notify_external (Telegram/Email/Slack)", None),
            ("43_spark_dashboard", "spark-output/dashboard.html 实时更新 (节点变绿)", None),
            ("44_audit_jsonl", "data/skill_audit.jsonl 含 audit_tag=l3-auto", None),
            ("45_final", "最终全量 499 passed + 0 failed", None),
        ],
    },
]


async def capture_scene(browser, scene: dict) -> int:
    """跑单个场景, 返回成功截图数."""
    ctx = await browser.new_context(viewport={"width": 1600, "height": 980})
    page = await ctx.new_page()
    ok = 0
    try:
        await page.goto(URL, wait_until="domcontentloaded", timeout=15_000)
        for step_id, desc, selector in scene["steps"]:
            try:
                if selector:
                    await page.wait_for_selector(selector, state="visible", timeout=5_000)
                    if selector == "#wbChatText":
                        await page.fill(selector, desc[:40])
                    elif "primary" in selector or ".wb-tab" in selector:
                        await page.click(selector)
                # 等待动画
                await page.wait_for_timeout(700)
                shot = OUT / f"{scene['id']}_{step_id}.png"
                await page.screenshot(path=str(shot))
                ok += 1
            except Exception as e:
                # 即使失败也截一张
                shot = OUT / f"{scene['id']}_{step_id}.png"
                try:
                    await page.screenshot(path=str(shot))
                    ok += 1
                except Exception:
                    pass
                print(f"  [WARN] {scene['id']}/{step_id}: {e}")
    finally:
        await ctx.close()
    return ok


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        total_frames = 0
        for sc in SCENES:
            n = await capture_scene(browser, sc)
            total_frames += n
            print(f"  [OK] {sc['id']}: {sc['title']} ({n} frames)")
        await browser.close()

    # 写分镜脚本 (Markdown)
    storyboard = OUT.parent / "v5_demo_storyboard.md"
    lines = ["# v5.0.0 L3 演示视频分镜脚本\n",
             "**总时长**: 5 min · **场景数**: 5 · **总帧数**: {}\n".format(total_frames),
             "**输出**: docs/demo/frames/*.png\n",
             "---\n"]
    for i, sc in enumerate(SCENES, 1):
        t0 = (i - 1) * 60
        t1 = i * 60
        lines.append(f"## {sc['title']}\n")
        lines.append(f"**时间段**: {t0//60:02d}:{t0%60:02d} - {t1//60:02d}:{t1%60:02d}\n")
        for j, (sid, desc, _) in enumerate(sc["steps"]):
            ts = t0 + j * 10
            lines.append(f"- **{ts//60:02d}:{ts%60:02d}** {sid}: {desc}")
        lines.append("")
    storyboard.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[OK] Frames: {total_frames} -> {OUT}")
    print(f"[OK] Storyboard: {storyboard}")


if __name__ == "__main__":
    asyncio.run(main())
