import os
import sqlite3
import asyncio
from typing import List, Dict

def _fetch_imessage_sync() -> List[Dict]:
    print("🔵 Fetching iMessage...")
    DB_PATH = os.path.expanduser("~/Library/Messages/chat.db")
    APPLE_EPOCH_OFFSET = 978307200
    messages = []
    
    import shutil
    temp_db = "/tmp/chat_copy.db"
    try:
        shutil.copy2(DB_PATH, temp_db)
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        query = """
        SELECT 
            message.text, 
            handle.id as sender, 
            message.date / 1000000000 as timestamp,
            chat.display_name as group_name
        FROM message
        LEFT JOIN handle ON message.handle_id = handle.ROWID
        LEFT JOIN chat_message_join ON message.ROWID = chat_message_join.message_id
        LEFT JOIN chat ON chat_message_join.chat_id = chat.ROWID
        WHERE (message.date / 1000000000 + 978307200) > strftime('%s', 'now', '-1 day')
        AND message.text IS NOT NULL
        ORDER BY message.date DESC;
        """
        cursor.execute(query)
        rows = cursor.fetchall()

        for row in rows:
            text, sender, ts, group_name = row
            messages.append({
                "platform": "iMessage",
                "channel": group_name if group_name else "Direct Message",
                "sender": sender if sender else "Me",
                "text": text,
                "ts": ts + APPLE_EPOCH_OFFSET
            })
        conn.close()
    except PermissionError as e:
        print(f"   iMessage Error: {e}")
        print("   \033[93mTo fix this, you must grant 'Full Disk Access' to your Terminal app:\033[0m")
        print("   1. Open System Settings -> Privacy & Security -> Full Disk Access")
        print("   2. Toggle on the switch for your terminal (e.g., Terminal, iTerm, VS Code, Cursor, etc.)")
        print("   3. Restart your terminal and run the command again.")
    except Exception as e:
        print(f"   iMessage Error: {e}")
    
    print(f"   Found {len(messages)} iMessage signals.")
    return messages

async def fetch_imessage() -> List[Dict]:
    return await asyncio.to_thread(_fetch_imessage_sync)
