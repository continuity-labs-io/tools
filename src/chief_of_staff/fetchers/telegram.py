import os
import datetime
from typing import List, Dict
from telethon import TelegramClient

async def fetch_telegram(api_id, api_hash) -> List[Dict]:
    print("🔵 Fetching Telegram...")
    if not api_id or not api_hash:
        print("   Skipping Telegram (No Credentials)")
        return []

    messages = []
    
    # Use an absolute path to secrets dir for the session file
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    session_path = os.path.join(base_dir, 'secrets', 'anon') # Telethon adds .session automatically

    try:
        # Pass the absolute path 'session_path' instead of just 'anon'
        async with TelegramClient(session_path, int(api_id), api_hash) as client:
            
            cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
            
            async for dialog in client.iter_dialogs(limit=50):
                try:
                    async for msg in client.iter_messages(dialog, offset_date=cutoff, reverse=True):
                        if msg.text:
                            sender = await msg.get_sender()
                            name = getattr(sender, 'first_name', None) or getattr(sender, 'title', 'Unknown')
                            messages.append({
                                "platform": "Telegram",
                                "channel": dialog.name,
                                "sender": name,
                                "text": msg.text,
                                "ts": msg.date.timestamp()
                            })
                except Exception:
                    continue
    except Exception as e:
        print(f"   Telegram Error: {e}")

    print(f"   Found {len(messages)} Telegram messages.")
    return messages
