import datetime
import feedparser
from typing import List, Dict

def fetch_federal_grants() -> List[Dict]:
    print("🔵 Fetching Federal Grants (SBIR/STTR)...")
    
    rss_url = "https://www.sbir.gov/rss/solicitations.xml"
    feed = feedparser.parse(rss_url)
    opportunities = []
    
    target_keywords = ["topological", "photonic", "neuromorphic", "compute", "novel architecture", "hopf"]
    
    for entry in feed.entries:
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
