# -*- coding: utf-8 -*-
"""screenshot_v51.py — v5.1.0 新 UI 截图 (模型面板 + 真 3D)."""
import asyncio
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.async_api import async_playwright

OUT = Path("docs/screenshots/v51")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8900/"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1600, "height": 980})
        page = await ctx.new_page()

        # 1. 默认状态
        await page.goto(URL, wait_until="domcontentloaded", timeout=15_000)
        await page.wait_for_selector(".wb-shell", state="visible")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=str(OUT / "01_v51_default.png"))
        print("  [OK] 01_v51_default.png")

        # 2. 选中 S1 + 切到 Approval tab (含 3D 预览)
        items = await page.query_selector_all(".wb-mail-item")
        if items:
            await items[0].click()
        await page.wait_for_timeout(500)
        await page.click(".wb-tab[data-itab='approval']", force=True)
        await page.wait_for_timeout(3000)  # 等 three.js 渲染 3D
        await page.screenshot(path=str(OUT / "02_3d_geometry.png"))
        print("  [OK] 02_3d_geometry.png (含真 3D 旋转)")

        # 3. 打开模型配置面板 (直接 toggle class, 避免点击错位)
        await page.evaluate("document.getElementById('wbModelsPanel').classList.add('open')")
        await page.wait_for_timeout(800)
        await page.screenshot(path=str(OUT / "03_models_panel.png"))
        print("  [OK] 03_models_panel.png (Timo v12 风格)")

        # 4. 关闭面板, 触发 Chat 进度条 (Chat 在右栏, 不需切 tab)
        await page.click("text=/模型/", force=True)
        await page.wait_for_timeout(300)
        # 强制 fill + 直接 eval 调 send (绕过点击, 模拟 Enter)
        await page.fill("#wbChatText", "verify this quote", force=True)
        await page.evaluate("document.querySelector('#wbChatText').dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter'}))")
        await page.wait_for_timeout(150)
        await page.screenshot(path=str(OUT / "04_progress_bar.png"))
        print("  [OK] 04_progress_bar.png (实时进度条)")

        # 5. AgentCache sys msg
        await page.wait_for_timeout(1500)
        await page.screenshot(path=str(OUT / "05_cache_status.png"))
        print("  [OK] 05_cache_status.png (AgentCache 状态)")

        await browser.close()
    print(f"\n[OK] All v5.1 screenshots: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
