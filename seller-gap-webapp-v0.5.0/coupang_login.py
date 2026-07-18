from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except Exception as exc:
    raise SystemExit("Playwright is not installed. Run install.bat first.") from exc

ROOT = Path(__file__).resolve().parent
PROFILE = ROOT / "data" / "browser-profile"
PROFILE.mkdir(parents=True, exist_ok=True)

with sync_playwright() as playwright:
    launch_options = {
        "user_data_dir": str(PROFILE),
        "headless": False,
        "locale": "ko-KR",
        "viewport": {"width": 1440, "height": 1000},
    }
    try:
        context = playwright.chromium.launch_persistent_context(channel="chrome", **launch_options)
    except Exception:
        context = playwright.chromium.launch_persistent_context(**launch_options)
    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://login.coupang.com/login/login.pang", wait_until="domcontentloaded", timeout=45000)
    print("Log in to Coupang in the opened Chrome window.")
    print("After login is complete, return here and press Enter.")
    input()
    context.close()
    print("Coupang login session was saved in data/browser-profile.")
