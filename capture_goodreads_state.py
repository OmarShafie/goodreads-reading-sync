#!/usr/bin/env python3
"""Open Goodreads for manual sign-in and save a Playwright storage state locally.

Run only on a trusted computer. The resulting JSON contains session cookies.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT = Path("goodreads-storage-state.json")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.goodreads.com/user/show/34901135", wait_until="domcontentloaded")
    print("\nSign in to Goodreads in the opened browser window.")
    print("When your signed-in Goodreads profile is visible, return here and press Enter.")
    input()
    if "goodreads.com" not in page.url or "sign_in" in page.url:
        raise SystemExit("Goodreads sign-in was not confirmed; no state file saved.")
    context.storage_state(path=str(OUTPUT))
    browser.close()

print(f"\nSaved {OUTPUT.resolve()}")
print("IMPORTANT: Treat this file like a password. Do not commit or share it.")
