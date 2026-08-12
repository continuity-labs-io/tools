# src/auth_x.py
import os
from playwright.sync_api import sync_playwright

def run():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    session_dir = os.path.join(base_dir, 'secrets', 'x_session')
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            session_dir,
            headless=False,  # Must be visible so you can manually log in
            viewport={'width': 1280, 'height': 800},
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"]
        )
        
        page = context.new_page()
        page.goto("https://x.com/login")
        
        print("🔵 Please log in to your X account in the browser window.")
        print("🔵 Once you are fully logged in and see your timeline, simply close the browser window.")
        
        try:
            # Keeps script running until you close the browser
            page.wait_for_event("close", timeout=0)
            print("✅ X session saved successfully!")
        except Exception:
            pass
            
        context.close()

if __name__ == "__main__":
    run()
