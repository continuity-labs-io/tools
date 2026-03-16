import os
import json
import argparse
import datetime
import asyncio
from typing import List, Dict
from dotenv import load_dotenv

import sys
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.append(base_dir)
from genai_client import get_client

# Import custom fetchers
from chief_of_staff.fetchers.slack import fetch_slack
from chief_of_staff.fetchers.telegram import fetch_telegram
from chief_of_staff.fetchers.gmail import fetch_gmail
from chief_of_staff.fetchers.arxiv import fetch_arxiv_papers
from chief_of_staff.fetchers.grants import fetch_federal_grants
from chief_of_staff.fetchers.whatsapp import fetch_whatsapp
from chief_of_staff.fetchers.imessage import fetch_imessage

# 1. Constants & Prompts
# Updated to match the ones in genai_client if needed, but keeping the ones from original script
MODEL_NAME = "gemini-3-pro-preview"

PROMPT_DAILY_BRIEFING_USER = "Here is the raw data dump. Generate my executive briefing."

WEIGHTED_KEYWORD_MATRIX = """
1. Entity & Operations (Weight: 40%): Continuity Labs, CODA, OPUS, incorporation, Delaware, cap table, IP assignment, SAFE, term sheet, counsel, equity, Stripe Atlas, Clerky.
2. Materials (Weight: 20%): AlGaAs, Lithium Niobate, LNOI, Tantalum Pentoxide, Silicon Nitride.
3. Structures (Weight: 20%): Microring resonator, Photonic crystal, Meta-surface, Non-Hermitian lattice.
4. Phenomena (Weight: 20%): Hopfion, Skyrmion, Berry curvature, Bound states in the continuum, Synthetic dimensions.
"""

PROMPT_CHIEF_OF_STAFF_SYSTEM = f"""
You are the Chief of Staff for the Founder and CEO of Continuity Labs, a deep-tech startup commercializing the 'Hopf Brain' photonic architecture through its core initiatives: CODA and OPUS. Your principal is currently navigating active company building and incorporation. 
Your goal is to provide a high-signal, low-noise executive briefing from the last 24 hours of data, balancing deep-tech R&D with the operational reality of company building.

### PRIORITIZATION LOGIC (The Weighted Attention Matrix)
1. **TIER 1: INCORPORATION & BUSINESS CRITICAL (iMessage, Gmail, High-Weight ArXiv)**
   - Elevate ANY communications regarding the legal, financial, or structural formation of CODA, OPUS, and Continuity Labs.
   - Treat direct requests, pending signatures, or updates from lawyers, co-founders, and investors as the absolute highest priority.
   - ArXiv papers with a 'Hopf Score' > 85% must be featured prominently.

2. **TIER 2: R&D, RESEARCH & GRANTS (Federal Feeds & Specialized Chats)**
   - Surface relevant technical correspondence, hardware supply chain updates, or federal grant opportunities (SBIR/STTR) that could serve as non-dilutive funding for Continuity Labs.

3. **TIER 3: BROAD CONTEXT (Telegram & WhatsApp)**
   - **Broadly Demote:** Treat these as secondary sources. Do NOT summarize social chatter, memes, or low-stakes group conversations.
   - **Exception Rule:** Only elevate a Telegram/WhatsApp message if it contains specific technical or corporate keywords: {WEIGHTED_KEYWORD_MATRIX}.

### OUTPUT STRUCTURE
- **Executive Summary:** A 1-paragraph synthesis of the 'State of the Union' for today, balancing business formation and technical progress.
- **Continuity Labs HQ (Ops & Incorporation):** Actionable updates, legal tasks, fundraising, and administrative blockers regarding Continuity Labs, CODA, and OPUS.
- **Topological & Hopf Signal:** Technical breakthroughs from ArXiv, specialized chats, or hardware grants.
- **Actionable Intelligence:** Direct requests, high-priority meetings, or pending documents requiring immediate signature/review.
- **The Noise Floor:** A very brief bulleted list of secondary items from Telegram/WhatsApp that *barely* made the cut.

Maintain a tone that is professional, resonant, and motivational. Use American spelling and present information primarily in paragraphs. State information affirmatively and avoid unnecessary corrective language.
"""

OUTPUT_DIR = os.path.expanduser("~/Downloads/chief_of_staff")

# --- CONFIGURATION ---
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project_root = os.path.dirname(base_dir)
env_path = os.path.join(project_root, 'secrets', '.env')
load_dotenv(dotenv_path=env_path)

# Load specific tokens for each workspace
SLACK_TOKENS = {
    k.replace("SLACK_TOKEN_", ""): v
    for k, v in os.environ.items()
    if k.startswith("SLACK_TOKEN_")
}

TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")

# --- MAIN AGGREGATOR & ANALYZER ---
async def main_async():    
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
    
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    # 2. Save Raw data (for history/debugging)
    output_file = os.path.join(OUTPUT_DIR, f"raw_data_{datetime.date.today()}.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_messages, f, indent=2, ensure_ascii=False)
    print(f"Raw data saved to {output_file} ({len(all_messages)} items)")

    # 3. Send to Gemini
    print("\nAnalyzing...")
    
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

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
