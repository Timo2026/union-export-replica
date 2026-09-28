"""Screenshot script: capture 6 frames showing Workbench v4 three-column UI."""
# -*- coding: utf-8 -*-
import sys, io, asyncio
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path("docs/screenshots")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8900/"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1600, "height": 980}, device_scale_factor=1)
        page = await ctx.new_page()

        await page.goto(URL, wait_until="networkidle")
        await page.wait_for_selector("#tab-workbench", state="visible")
        await page.wait_for_selector(".wb-shell", state="visible")
        await page.wait_for_timeout(400)
        await page.screenshot(path=str(OUT / "01_default.png"), full_page=False)
        print("  [ok] 01_default.png")

        await page.click(".wb-mail-item:nth-child(1)")
        await page.wait_for_timeout(300)
        await page.screenshot(path=str(OUT / "02_s1_pass.png"))
        print("  [ok] 02_s1_pass.png")

        await page.click(".wb-mail-item:nth-child(2)")
        await page.wait_for_timeout(200)
        await page.click(".wb-tab[data-itab='approval']")
        await page.wait_for_timeout(300)
        await page.screenshot(path=str(OUT / "03_s2_hitl.png"))
        print("  [ok] 03_s2_hitl.png")

        await page.click(".wb-tab[data-itab='mail']")
        await page.wait_for_timeout(150)
        await page.fill("#wbChatText", "calc quote for this mail")
        await page.click(".wb-chat-input .row .primary")
        await page.wait_for_timeout(900)
        await page.screenshot(path=str(OUT / "04_chat_calc_quote.png"))
        print("  [ok] 04_chat_calc_quote.png")

        await page.fill("#wbChatText", "approve this quote")
        await page.click(".wb-chat-input .row .primary")
        await page.wait_for_timeout(900)
        await page.screenshot(path=str(OUT / "05_chat_approve.png"))
        print("  [ok] 05_chat_approve.png")

        await page.click("text=/Skills/")
        await page.wait_for_timeout(500)
        await page.screenshot(path=str(OUT / "06_skill_console.png"))
        print("  [ok] 06_skill_console.png")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

