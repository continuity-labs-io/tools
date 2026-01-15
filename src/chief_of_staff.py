import os
import json
import argparse
import datetime
import asyncio
from typing import List, Dict
from dotenv import load_dotenv

# Libraries
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from telethon import TelegramClient
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from genai_client import get_client

# 1. Define your System Instruction (The Persona)
# We use triple quotes (""") to handle the multi-line text cleanly.
chief_of_staff_prompt = """
You are the user's Chief of Staff. Your goal is to apply the Eisenhower Matrix to a "fire hose" of raw message data (Slack, Telegram, Email) and filter out 90% of the noise.

**Input Data:**
The user will provide a JSON dump or text stream of messages from the last 24 hours.

**Your Processing Logic:**
1.  Scan every message.
2.  Discard anything that is:
    * Newsletters / Marketing / Spam.
    * Automated alerts (CI/CD, Jira) unless they indicate a critical failure.
    * "Thank you" / "Sounds good" / Low-signal social chatter.
3.  Group related messages (e.g., 5 Slack DMs from the same person about the same topic = 1 item).
4.  Categorize the remaining signal into the formats below.

**Output Format (Strict Markdown):**

# 🔴 Urgent & Important (Do Now)
* **[Platform] Sender Name:** [One-sentence summary of the fire].
    * *Context:* [Brief detail if needed]
    * *Action:* [What needs to be done?]

# 🟡 Not Urgent but Important (Schedule)
* **[Platform] Sender Name:** [Summary of proposal/document to review].
    * *Link:* [Insert Link if available]

# 🔵 Urgent but Not Important (Delegate)
* **[Platform] Sender Name:** [Request for access/info that can be delegated].

# 🟢 Clarifications (Optional)
* *List any ambiguous items where you cannot determine urgency without more info.*

**Tone:**
Direct, executive, and concise. No fluff. If the inbox is empty of urgent items, state "All clear."
"""

OUTPUT_DIR = os.path.expanduser("~/gh")
CONFIG_DIR = os.path.expanduser("~/.config/chief_of_staff")

# --- CONFIGURATION ---
load_dotenv()

# Load specific tokens for each workspace
SLACK_TOKENS = {
    k.replace("SLACK_TOKEN_", ""): v
    for k, v in os.environ.items()
    if k.startswith("SLACK_TOKEN_")
}

TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")
TELEGRAM_SESSION = "anon"

TELEGRAM_SESSION = "anon"

# GEMINI_API_KEY is now handled by genai_client

# Time window: Last 24 hours
ONE_DAY_AGO = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
TIMESTAMP_CUTOFF = ONE_DAY_AGO.timestamp()

# --- 1. SLACK FETCHER (Updated for Multi-Workspace) ---
def fetch_slack(token: str, workspace_name: str) -> List[Dict]:
    print(f"🔵 Fetching Slack ({workspace_name})...")
    if not token:
        print(f"   Skipping {workspace_name} (No Token)")
        return []
    
    client = WebClient(token=token)
    messages = []
    
    try:
        # Get list of channels
        result = client.conversations_list(types="public_channel,private_channel,im,mpim", limit=100)
        
        for channel in result["channels"]:
            if channel["is_archived"]: continue
                
            try:
                history = client.conversations_history(
                    channel=channel["id"],
                    oldest=TIMESTAMP_CUTOFF,
                    limit=20
                )
                
                for msg in history["messages"]:
                    if "user" in msg:
                        # Label platform as 'Slack (LBF)' etc.
                        messages.append({
                            "platform": f"Slack ({workspace_name})", 
                            "channel": channel.get("name_normalized") or "DM",
                            "sender": msg.get("user"),
                            "text": msg.get("text"),
                            "ts": float(msg["ts"])
                        })
            except SlackApiError:
                continue
                
    except SlackApiError as e:
        print(f"   Slack Error: {e.response['error']}")

    print(f"   Found {len(messages)} messages in {workspace_name}.")
    return messages

# --- 2. TELEGRAM FETCHER ---
async def fetch_telegram(api_id, api_hash) -> List[Dict]:
    print("🔵 Fetching Telegram...")
    if not api_id or not api_hash:
        print("   Skipping Telegram (No Credentials)")
        return []

    messages = []
    async with TelegramClient(TELEGRAM_SESSION, api_id, api_hash) as client:
        async for dialog in client.iter_dialogs(limit=20):
            async for msg in client.iter_messages(dialog, offset_date=ONE_DAY_AGO, reverse=True):
                if msg.text:
                    sender = await msg.get_sender()
                    name = sender.first_name if sender else "Unknown"
                    messages.append({
                        "platform": "Telegram",
                        "channel": dialog.name,
                        "sender": name,
                        "text": msg.text,
                        "ts": msg.date.timestamp()
                    })
    
    print(f"   Found {len(messages)} Telegram messages.")
    return messages

# --- 3. GMAIL FETCHER ---
def fetch_gmail() -> List[Dict]:
    print("Fetching Gmail...")
    SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
    creds = None
    messages = []
    
    token_path = os.path.join(CONFIG_DIR, 'token.json')
    creds_path = os.path.join(CONFIG_DIR, 'credentials.json')

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(creds_path):
                print(f"   Skipping Gmail (No credentials.json found in {CONFIG_DIR})")
                return []
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    try:
        service = build('gmail', 'v1', credentials=creds)
        results = service.users().messages().list(userId='me', q='newer_than:1d').execute()
        msg_ids = results.get('messages', [])

        for msg_meta in msg_ids:
            msg = service.users().messages().get(userId='me', id=msg_meta['id']).execute()
            headers = msg['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "(No Subject)")
            sender = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown")
            
            messages.append({
                "platform": "Gmail",
                "channel": "Inbox",
                "sender": sender,
                "text": f"Subject: {subject}\nSnippet: {msg.get('snippet', '')}",
                "ts": int(msg['internalDate']) / 1000
            })

    except Exception as e:
        print(f"   Gmail Error: {e}")

    print(f"   Found {len(messages)} Gmail messages.")
    return messages

# --- MAIN AGGREGATOR & ANALYZER ---
async def main():
    print(f"Starting Chief of Staff Dump for {datetime.date.today()}...")
    
    all_messages = []

    # 1. Fetch Data
    parser = argparse.ArgumentParser(description="Chief of Staff - Daily Briefing Generator")
    parser.add_argument(
        "--sources", 
        nargs="+", 
        default=["gmail", "slack", "telegram"],
        choices=["gmail", "slack", "telegram"],
        help="Specify which data sources to fetch (default: all)"
    )
    args = parser.parse_args()

    # Uncomment these to enable Slack/Telegram when you are ready
    if "slack" in args.sources:
        for name, token in SLACK_TOKENS.items():
            all_messages.extend(fetch_slack(token, name))
    
    if "telegram" in args.sources:
        all_messages.extend(await fetch_telegram(TELEGRAM_API_ID, TELEGRAM_API_HASH))
    
    if "gmail" in args.sources:
        all_messages.extend(fetch_gmail())
    
    if not all_messages:
        print("No messages found.")
        return
    
    # 2. Save Raw Dump (for history/debugging)
    output_file = os.path.join(OUTPUT_DIR, f"daily_dump_{datetime.date.today()}.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_messages, f, indent=2, ensure_ascii=False)
    print(f"Raw dump saved to {output_file} ({len(all_messages)} items)")

    # 3. Send to Gemini
    print("\nChief of Staff (Gemini) is analyzing...")
    
    try:
        client = get_client()
        
        # Read the JSON file content
        with open(output_file, "r", encoding="utf-8") as f:
            json_content = f.read()
        
        # Generate Briefing
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            config={"system_instruction": chief_of_staff_prompt},
            contents=[json_content, "Here is the raw data dump. Generate my executive briefing."]
        )

        # Print to Terminal
        print("\n" + "="*50)
        print("DAILY BRIEFING")
        print("="*50 + "\n")
        print(response.text)
        print("\n" + "="*50)

        # Optional: Save Briefing to Markdown
        briefing_file = os.path.join(OUTPUT_DIR, f"daily_briefing_{datetime.date.today()}.md")
        with open(briefing_file, "w", encoding="utf-8") as f:
            f.write(response.text)
        print(f"Briefing saved to {briefing_file}")

    except Exception as e:
        print(f"Analysis Failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())