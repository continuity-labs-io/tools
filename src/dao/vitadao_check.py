#!/usr/bin/env python3
import requests
import sys

# --- CONFIG ---
FORUM_URL = "https://gov.vitadao.com/latest.json"
# Keywords that signal "Money" or "Opportunity"
KEYWORDS = ["base", "airdrop", "ipt", "token", "whitelist", "presale", "aubrai", "bio"]

def check_forum_alpha():
    print(f"📡 Scanning VitaDAO Governance Forum (Sorted by Date)...")
    try:
        resp = requests.get(FORUM_URL)
        resp.raise_for_status()
        data = resp.json()
        
        topics = data['topic_list']['topics']
        
        # --- THE FIX: SORT BY CREATION DATE (DESCENDING) ---
        # We parse the string 'created_at' to ensure 2025 comes before 2024
        topics.sort(key=lambda x: x['created_at'], reverse=True)
        
        print(f"{'='*80}")
        print(f"{'DATE':<12} {'VIEWS':<8} {'TITLE'}")
        print(f"{'='*80}")

        found_alpha = False
        
        # We take the top 15 *after* sorting
        for t in topics[:15]: 
            title = t['title']
            views = t['views']
            date_str = t['created_at'][:10] # YYYY-MM-DD
            slug = t['slug']
            
            # Check for Money Keywords
            is_alpha = any(k in title.lower() for k in KEYWORDS)
            
            if is_alpha:
                found_alpha = True
                # Green Text for Alpha
                print(f"\033[1;32m{date_str:<12} {views:<8} {title}\033[0m") 
                print(f"   ↳ LINK: https://gov.vitadao.com/t/{slug}/{t['id']}")
            else:
                # Standard Text
                print(f"{date_str:<12} {views:<8} {title}")

        print(f"{'='*80}")
        
        if found_alpha:
            print("\n🚨 ALPHA DETECTED: Check the green links above.")
        else:
            print("\n💤 No immediate 'money' keywords found in the newest 15 posts.")

    except Exception as e:
        print(f"❌ Error reading forum: {e}")

if __name__ == "__main__":
    check_forum_alpha()

