import os
import datetime
from typing import List, Dict
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

ONE_DAY_AGO = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
TIMESTAMP_CUTOFF = ONE_DAY_AGO.timestamp()

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
