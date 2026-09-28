# -*- coding: utf-8 -*-
"""screenshot_v6.py — v6.0.0 融合版截图 (根 index.html, 真接线 5 endpoints).

跑 3 个场景 (PASS / HITL / BLOCKED), 各 2 张截图 = 6 张.
依赖: pip install playwright + python -m playwright install chromium
"""
import asyncio
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from playwright.async_api import async_playwright

OUT = Path("docs/screenshots/v6")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8900/"  # v6 根 index.html (FastAPI 优先返)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1600, "height": 980})
        page = await ctx.new_page()

        # 1. 融合版 v6 入口 (默认)
        await page.goto(URL, wait_until="domcontentloaded", timeout=15_000)
        await page.wait_for_selector("#inboxList", state="visible")
        await page.wait_for_timeout(2000)  # 等 fetch
        await page.screenshot(path=str(OUT / "01_v6_root_default.png"))
        print("  [OK] 01_v6_root_default.png (v6 融合版根入口)")

        # 2. 选中 S1 (PASS) → Inspector 8 区
        items = await page.query_selector_all(".item")
        if items:
            await items[0].click(force=True)
            await page.wait_for_timeout(1500)
            await page.screenshot(path=str(OUT / "02_s1_pass_8zones.png"))
            print("  [OK] 02_s1_pass_8zones.png (PASS 8 区)")

        # 3. Chat 发送触发 + 黄金链激活
        await page.fill("#chatTa", "verify this quote", force=True)
        await page.evaluate("document.getElementById('chatTa').dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter'}))")
        await page.wait_for_timeout(1500)
        await page.screenshot(path=str(OUT / "03_chat_verify_cache.png"))
        print("  [OK] 03_chat_verify_cache.png (Chat + Cache 统计)")

        # 4. legacy 路径 (webui)
        await page.goto(URL + "webui", wait_until="domcontentloaded", timeout=15_000)
        await page.wait_for_timeout(2000)
        await page.screenshot(path=str(OUT / "04_legacy_webui.png"))
        print("  [OK] 04_legacy_webui.png (legacy webui fallback)")

        # 5. /v1/cache/stats 含 nvidia:health (F7 mock)
        # 6. /v1/spark/dashboard
        # (单独 endpoint 测试用 curl 即可, 不必 Playwright)

        await browser.close()
    print(f"\n[OK] All v6 screenshots: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
