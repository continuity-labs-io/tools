import os
import json
import argparse
import datetime
import asyncio
from typing import List, Dict
from dotenv import load_dotenv
import feedparser
import urllib.parse
import requests
import sqlite3
import time

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
from playwright.async_api import async_playwright

# 1. Constants & Prompts
MODEL_NAME = "gemini-2.0-flash"

PROMPT_ARXIV_DEEP_RESEARCH = (
    "Analyze this paper. Provide a structured summary including: "
    "Core Innovation, Key Technical Implementation Details, and "
    "Relevance to Topological Compute/Hopf Architectures."
)

PROMPT_DAILY_BRIEFING_USER = "Here is the raw data dump. Generate my executive briefing."

WEIGHTED_KEYWORD_MATRIX = """
1. Materials (Weight: 20%): AlGaAs, Lithium Niobate, LNOI, Tantalum Pentoxide, Silicon Nitride.
2. Structures (Weight: 30%): Microring resonator, Photonic crystal, Meta-surface, Non-Hermitian lattice.
3. Phenomena (Weight: 50%): Hopfion, Skyrmion, Berry curvature, Bound states in the continuum, Synthetic dimensions.
"""

PROMPT_ARXIV_SCORING_SYSTEM = f"""
You are a Senior Hardware Architect specializing in Topological Computing and Hopf Architectures.
Your goal is to evaluate the provided research paper against a specific Weighted Keyword Matrix and determine its relevance to the user's goals.

**Weighted Keyword Matrix:**
{WEIGHTED_KEYWORD_MATRIX}

**Scoring Criteria (0-100):**
- **Hardware Feasibility:** Can this be fabricated on-chip? (Is it theoretical only, or are there experimental results/clear pathways to fabrication?)
- **Topological Robustness:** Does it utilize true topological protection (e.g., backscattering immunity, topological invariants)?
- **Hopf Connection:** Does it relate to Hopf Fibration, 3D topological solitons (Hopfions), or high-dimensional topological states?

**Output Format:**
Return a JSON object with the following fields:
- `relevance_score` (int): 0-100.
- `justification` (string): Brief explanation of the score.
- `hardware_feasibility` (string): Assessment of fabrication potential.
- `topological_robustness` (string): Assessment of topological properties.
- `hopf_connection` (string): Assessment of relevance to Hopf/3D topology.
- `catch` (string): The "Catch" - potential fabrication hurdle, theoretical limitation, or scalability issue.
- `summary` (string): A concise summary of the paper's core innovation.
"""

PROMPT_CHIEF_OF_STAFF_SYSTEM = f"""
You are the Chief of Staff for a PhD-level Hardware Architect and Founder focused on the 'Hopf Brain' photonic architecture and substrate independence. Your goal is to provide a high-signal, low-noise briefing from the last 24 hours of data.

### PRIORITIZATION LOGIC (The Weighted Attention Matrix)
1. **TIER 1: CRITICAL SIGNAL (iMessage & High-Weight ArXiv)**
   - Treat iMessages as the highest priority personal/professional signal. Elevate direct requests or updates from human contacts here.
   - ArXiv papers with a 'Hopf Score' > 85% must be featured prominently.

2. **TIER 2: RESEARCH & GRANTS (Gmail & Federal Feeds)**
   - Surface relevant technical correspondence or grant opportunities.

3. **TIER 3: BROAD CONTEXT (Telegram & WhatsApp)**
   - **Broadly Demote:** Treat these as secondary sources. Do NOT summarize social chatter, memes, or low-stakes group conversations.
   - **Exception Rule:** Only elevate a Telegram/WhatsApp message if it contains specific technical keywords: {WEIGHTED_KEYWORD_MATRIX}.

### OUTPUT STRUCTURE
- **Executive Summary:** A 1-paragraph synthesis of the 'State of the Union' for today.
- **Topological & Hopf Signal:** Technical breakthroughs from ArXiv or specialized chats.
- **Actionable Intelligence:** Direct requests or high-priority meetings from iMessage/Gmail.
- **The Noise Floor:** A very brief bulleted list of secondary items from Telegram/WhatsApp that *barely* made the cut.

Maintain a tone that is professional, resonant, and motivational. Use American spelling and present information primarily in paragraphs. Avoid unnecessary corrective language.
"""

OUTPUT_DIR = os.path.expanduser("~/Downloads/chief_of_staff")
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
    """
    Authenticates with Telegram and retrieves messages from the last 24 hours.
    """
    print("🔵 Fetching Telegram...")
    if not api_id or not api_hash:
        print("   Skipping Telegram (No Credentials)")
        return []

    messages = []
    # Ensure api_id is an integer for Telethon
    api_id_int = int(api_id)
    
    # 'anon' is the session name; it creates a local 'anon.session' file
    async with TelegramClient('anon', api_id_int, api_hash) as client:
        # .start() handles the interactive login (phone, code, 2FA) in the terminal
        await client.start()
        
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
        
        # limit=50 scans your 50 most recently active chats
        async for dialog in client.iter_dialogs(limit=50):
            try:
                # offset_date ensures we only pull recent signal
                async for msg in client.iter_messages(dialog, offset_date=cutoff, reverse=True):
                    if not msg.text:
                        continue
                        
                    sender = await msg.get_sender()
                    # Resolve sender name affirmatively
                    name = "Unknown"
                    if sender:
                        name = getattr(sender, 'first_name', None) or getattr(sender, 'title', 'Unknown')
                    
                    messages.append({
                        "platform": "Telegram",
                        "channel": dialog.name,
                        "sender": name,
                        "text": msg.text,
                        "ts": msg.date.timestamp()
                    })
            except Exception as e:
                # Skip individual chats with restricted access or errors
                continue
    
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

# Core research keywords for Hopf Architecture & Topological Compute
RESEARCH_DRAGNET = {
    "math": [
        "Hopf fibration", 
        "topological compute"
    ],
    "materials": [
        "AlGaAs", 
        "Lithium Niobate", 
        "LNOI", 
        "Chalcogenide", 
        "Silicon Nitride"
    ],
    "structures": [
        "Microring resonator", 
        "Photonic crystal", 
        "Topological insulator", 
        "Meta-surface"
    ],
    "phenomena": [
        "Skyrmion", 
        "Hopfion", 
        "Berry curvature", 
        "Bound states in the continuum", 
        "Synthetic dimensions"
    ]
}

# --- 4. SCIENCE OFFICER (ArXiv) ---
def fetch_arxiv_papers(top_n=5) -> List[Dict]:
    print("🔵 Fetching ArXiv Research (Deep Mode)...")
    
    # We construct a query for your niche interests
    # Flatten the RESEARCH_DRAGNET dictionary values into a single list of keywords
    keywords = [k for category in RESEARCH_DRAGNET.values() for k in category]
    query = "+OR+".join([urllib.parse.quote(k) for k in keywords])
    
    # ArXiv API is basically an RSS feed
    url = f'http://export.arxiv.org/api/query?search_query=all:{query}&start=0&max_results=5&sortBy=submittedDate&sortOrder=descending'
    
    feed = feedparser.parse(url)
    analyzed_papers = []
    
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    client = get_client()

    # Limit to top N for deep research
    for entry in feed.entries[:top_n]:
        print(f"> {entry.title[:50]}...")
        
        # 1. Find PDF Link
        pdf_link = None
        for link in entry.links:
            if link.type == 'application/pdf':
                pdf_link = link.href
                break
        
        # Fallback: Convert /abs/ to /pdf/
        if not pdf_link:
            pdf_link = entry.link.replace("/abs/", "/pdf/") + ".pdf"
            
        # 2. Download PDF
        filename = os.path.join(OUTPUT_DIR, f"{entry.id.split('/')[-1]}.pdf")
        try:
            response = requests.get(pdf_link)
            with open(filename, 'wb') as f:
                f.write(response.content)
            
            # 3. Upload to Gemini
            pdf_file = client.files.upload(file=filename)
            
            # Wait for processing
            while pdf_file.state.name == "PROCESSING":
                time.sleep(2)
                pdf_file = client.files.get(name=pdf_file.name)
                
            if pdf_file.state.name == "FAILED":
                print("      PDF processing failed.")
                continue
                
            # 4. Generate Deep Summary (JSON)
            response = client.models.generate_content(
                model=MODEL_NAME,
                config={
                    "system_instruction": PROMPT_ARXIV_SCORING_SYSTEM,
                    "response_mime_type": "application/json"
                },
                contents=[pdf_file, "Analyze this paper."]
            )
            
            analysis = json.loads(response.text)
            if isinstance(analysis, list):
                analysis = analysis[0]
                
            analysis['title'] = entry.title
            analysis['link'] = entry.link
            analysis['author'] = entry.author
            analyzed_papers.append(analysis)
            
        except Exception as e:
            print(f"      Failed to process {entry.title}: {e}")
            
    # 5. Rank and Filter
    analyzed_papers.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
    
    minscore = 10
    breakthrough_score = 50
    final_messages = []
    for p in analyzed_papers:
        score = p.get('relevance_score', 0)
        if score < minscore:
            continue
            
        signal_prefix = "🚨 BREAKTHROUGH SIGNAL" if score > breakthrough_score else f"{score}% Match"
        
        formatted_text = (
            f"**{signal_prefix}: {p['title']}**\n"
            f"*   **Why it matters:** {p.get('hopf_connection', 'N/A')}\n"
            f"*   **The Catch:** {p.get('catch', 'N/A')}\n"
            f"*   **Summary:** {p.get('summary', 'N/A')}\n"
            f"*   **Link:** {p['link']}"
        )
        
        final_messages.append({
            "platform": "ArXiv",
            "channel": "Research",
            "sender": p['author'],
            "text": formatted_text,
            "ts": datetime.datetime.now().timestamp()
        })
        
    print(f"   Processed {len(final_messages)} relevant papers (out of {len(analyzed_papers)} analyzed).")
    return final_messages

# --- 5. PROCUREMENT OFFICER (Grants.gov / SBIR) ---
def fetch_federal_grants() -> List[Dict]:
    print("🔵 Fetching Federal Grants (SBIR/STTR)...")
    
    # SBIR.gov RSS Feed (Small Business Innovation Research - where the DoD money lives)
    # This is a general feed, but we can filter it in Python or let Gemini filter it.
    # A more targeted approach is scraping, but RSS is safer for scripts.
    rss_url = "https://www.sbir.gov/rss/solicitations.xml"
    
    feed = feedparser.parse(rss_url)
    opportunities = []
    
    target_keywords = ["topological", "photonic", "neuromorphic", "compute", "novel architecture", "hopf"]
    
    for entry in feed.entries:
        # Simple keyword filter before we even bother Gemini
        content = (entry.title + entry.summary).lower()
        if any(k in content for k in target_keywords):
            opportunities.append({
                "platform": "GovGrants",
                "channel": "Funding",
                "sender": "US Govt",
                "text": f"Grant: {entry.title}\nDetails: {entry.summary}\nLink: {entry.link}",
                "ts": datetime.datetime.now().timestamp()
            })
            
    print(f"   Found {len(opportunities)} relevant grants.")
    return opportunities

# --- 6. WHATSAPP FETCHER (Async Version) ---
async def fetch_whatsapp() -> List[Dict]:
    print("🔵 Fetching WhatsApp (Async Mode)...")
    session_dir = os.path.expanduser("~/gh/tools/src/whatsapp_session")
    
    if not os.path.exists(session_dir):
        print("   Skipping WhatsApp (No session found)")
        return []

    messages = []
    async with async_playwright() as p:
        # We specify a modern Chrome User Agent to bypass the "Update Chrome" error
        context = await p.chromium.launch_persistent_context(
            session_dir, 
            headless=True,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        page = await context.new_page()
        
        try:
            # wait_until="networkidle" ensures the page is fully loaded before we look for elements
            await page.goto("https://web.whatsapp.com", wait_until="networkidle", timeout=60000)
            
            print("   Waiting for chat interface...")
            await page.wait_for_selector("#pane-side", timeout=45000)
            
            # Scrape the top dozen listitems
            chats = await page.query_selector_all("div[role='listitem']")
            for chat in chats[:12]:
                try:
                    title_element = await chat.query_selector("span[title]")
                    chat_name = await title_element.get_attribute("title") if title_element else "Unknown"
                    
                    # Selector for the last message preview
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

# --- 7. IMESSAGE FETCHER (Async-wrapped) ---
async def fetch_imessage() -> List[Dict]:
    # Wrapping synchronous SQLite in a thread to prevent blocking the async loop
    return await asyncio.to_thread(_fetch_imessage_sync)

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
    except Exception as e:
        print(f"   iMessage Error: {e}")
    
    print(f"   Found {len(messages)} iMessage signals.")
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
        default=["slack", "telegram", "whatsapp", "gmail", "imessage", "arxiv", "govgrants"],
        choices=["slack", "telegram", "whatsapp", "gmail", "imessage", "arxiv", "govgrants"],
        help="Specify which data sources to fetch (default: all)"
    )
    args = parser.parse_args()

    # Uncomment these to enable Slack/Telegram when you are ready
    if "slack" in args.sources:
        for name, token in SLACK_TOKENS.items():
            all_messages.extend(fetch_slack(token, name))
    
    if "telegram" in args.sources:
        all_messages.extend(await fetch_telegram(TELEGRAM_API_ID, TELEGRAM_API_HASH))
    
    if "whatsapp" in args.sources:
        all_messages.extend(await fetch_whatsapp())

    if "gmail" in args.sources:
        all_messages.extend(fetch_gmail())
    
    if "imessage" in args.sources:
        all_messages.extend(await fetch_imessage())
    
    if "arxiv" in args.sources:
        all_messages.extend(fetch_arxiv_papers())
    
    if "govgrants" in args.sources:
        all_messages.extend(fetch_federal_grants())
    
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
            model=MODEL_NAME,
            config={"system_instruction": PROMPT_CHIEF_OF_STAFF_SYSTEM},
            contents=[json_content, PROMPT_DAILY_BRIEFING_USER]
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
