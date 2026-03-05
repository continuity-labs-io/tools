import os
import datetime
from typing import List, Dict
from playwright.async_api import async_playwright

async def fetch_whatsapp() -> List[Dict]:
    print("🔵 Fetching WhatsApp (Async Mode)...")
    # Link to the new secrets directory
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    session_dir = os.path.join(base_dir, 'secrets', 'whatsapp_session')
    
    if not os.path.exists(session_dir):
        print("   Skipping WhatsApp (No session found)")
        return []

    messages = []
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            session_dir, 
            headless=True,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        page = await context.new_page()
        
        try:
            await page.goto("https://web.whatsapp.com", wait_until="networkidle", timeout=60000)
            
            print("   Waiting for chat interface...")
            await page.wait_for_selector("#pane-side", timeout=45000)
            
            chats = await page.query_selector_all("div[role='listitem']")
            for chat in chats[:12]:
                try:
                    title_element = await chat.query_selector("span[title]")
                    chat_name = await title_element.get_attribute("title") if title_element else "Unknown"
                    
                    msg_element = await chat.query_selector("span[dir='ltr']")
                    msg_text = await msg_element.inner_text() if msg_element else ""
                    
                    if msg_text:
                        messages.append({
                            "platform": "WhatsApp",
                            "channel": chat_name,
                            "sender": chat_name,
                            "text": msg_text.strip(),
                            "ts": datetime.datetime.now().timestamp()
                        })
                except Exception:
                    continue
        except Exception as e:
            await page.screenshot(path="whatsapp_error_debug.png")
            print(f"   WhatsApp Error: {e}")
        finally:
            await context.close()
            
    print(f"   Found {len(messages)} WhatsApp messages.")
    return messages
