# save_session.py
from playwright.sync_api import sync_playwright
from pathlib import Path
import time

CHROME_EXECUTABLE_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

SESSION_FILE = "x_full_session.json"

def save_full_x_session():
    print("Starting session saver...")
    print("→ This script opens a real Chrome window.")
    print("→ Log in to X if needed → wait until home feed is fully loaded.")
    print("→ Optional but recommended: manually open compose, type something, post 1 tweet → this 'warms up' the session.")
    print("→ When ready → press Enter in this terminal to save...\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            executable_path=CHROME_EXECUTABLE_PATH,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        )

        page = context.new_page()
        page.goto("https://x.com/home", timeout=90000, wait_until="networkidle")

        # Give user time to log in / interact
        input("Press Enter when ready to save session... ")

        # Optional: small wait to make sure everything settled
        time.sleep(3)

        # Save full storage state (cookies + localStorage + indexedDB + ...)
        context.storage_state(path=SESSION_FILE)
        print(f"\nSession successfully saved to: {SESSION_FILE.absolute()}")

        browser.close()


if __name__ == "__main__":
    if Path(SESSION_FILE).exists():
        print(f"Warning: {SESSION_FILE} already exists.")
        overwrite = input("Overwrite existing session? (y/n): ").strip().lower()
        if overwrite != 'y':
            print("Aborted.")
            exit(0)

    save_full_x_session()
