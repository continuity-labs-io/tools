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
from chief_of_staff.fetchers.x_list import fetch_x_list

# 1. Constants & Prompts
# Updated to match the ones in genai_client if needed, but keeping the ones from original script
MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

from chief_of_staff.prompts import (
    PROMPT_DAILY_BRIEFING_USER,
    PROMPT_CHIEF_OF_STAFF_SYSTEM
)

OUTPUT_DIR = os.path.expanduser("~/Downloads/cos")

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
        default=["slack", "telegram", "whatsapp", "gmail", "imessage", "arxiv", "govgrants", "xlist"],
        choices=["slack", "telegram", "whatsapp", "gmail", "imessage", "arxiv", "govgrants", "xlist"],
        help="Specify which data sources to fetch (default: all)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=3,
        help="Number of days to look back for data (default: 3)"
    )
    parser.add_argument(
        "--xlist-url",
        type=str,
        default="https://x.com/i/lists/1477865252754653188",
        help="URL of the X list to fetch"
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

    if "xlist" in args.sources:
        all_messages.extend(await fetch_x_list(target_list_url=args.xlist_url, days=args.days))

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
        from genai_client import get_best_model
        
        # Read the JSON file content
        with open(output_file, "r", encoding="utf-8") as f:
            json_content = f.read()
        
        # Generate Briefing
        model_name = get_best_model(client, MODEL_NAME)
        try:
            response = client.models.generate_content(
                model=model_name,
                config={"system_instruction": PROMPT_CHIEF_OF_STAFF_SYSTEM},
                contents=[json_content, PROMPT_DAILY_BRIEFING_USER]
            )
        except Exception as e:
            fallback_model = "gemini-3.5-flash"
            print(f"Warning: Primary model {MODEL_NAME} failed ({e}). Falling back to {fallback_model}...")
            response = client.models.generate_content(
                model=fallback_model,
                config={"system_instruction": PROMPT_CHIEF_OF_STAFF_SYSTEM},
                contents=[json_content, PROMPT_DAILY_BRIEFING_USER]
            )

        # Print to Terminal
        print("\nSummary\n")
        print(response.text, "\n")

        # Optional: Save Briefing to Markdown
        briefing_file = os.path.join(OUTPUT_DIR, f"summary_{datetime.date.today()}.md")
        with open(briefing_file, "w", encoding="utf-8") as f:
            f.write(response.text)

    except Exception as e:
        print(f"Analysis Failed: {e}")

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
