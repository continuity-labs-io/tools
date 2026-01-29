from playwright.sync_api import sync_playwright
import os

def run():
    # Define the session directory
    session_dir = os.path.expanduser("~/gh/tools/src/whatsapp_session")
    
    with sync_playwright() as p:
        # Launch a persistent browser context
        context = p.chromium.launch_persistent_context(
            session_dir,
            headless=False  # Must be False to see and scan the QR code
        )
        
        page = context.new_page()
        page.goto("https://web.whatsapp.com")
        
        print("Please scan the QR code on your screen...")
        
        # Wait for the main chat interface to load (indicating successful login)
        try:
            page.wait_for_selector("div[contenteditable='true']", timeout=0)
            print("Successfully authenticated. Closing browser.")
        except Exception as e:
            print(f"Authentication timed out or failed: {e}")
        
        context.close()

if __name__ == "__main__":
    run()
