# src/chief_of_staff/fetchers/x_list.py
import os
import sys
import json
import asyncio
import datetime
from typing import List, Dict
from playwright.async_api import async_playwright

# Ensure genai_client is importable
base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if base_dir not in sys.path:
    sys.path.append(base_dir)
from genai_client import get_client
import logging

logger = logging.getLogger(__name__)

from chief_of_staff.prompts import PROMPT_X_FILTER_SYSTEM
async def fetch_x_list(target_list_url: str = "https://x.com/i/lists/1477865252754653188", days: int = 1) -> List[Dict]:
    print(f"🔵 Fetching X List (Past {days} days)...")
    
    session_dir = os.path.join(base_dir, 'secrets', 'x_session')
    if not os.path.exists(session_dir):
        print("   ❌ Skipping X List (No session found. Run src/auth_x.py first.)")
        return []


    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    tweets_dict = {}  # Using a dict to deduplicate tweets by URL as we scroll
    
    async with async_playwright() as p:
        logger.debug("   [DEBUG] Launching Playwright persistent context...")
        context = await p.chromium.launch_persistent_context(
            session_dir, 
            headless=True,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        logger.debug("   [DEBUG] Context launched successfully. Opening new page...")
        page = await context.new_page()
        
        try:
            logger.debug(f"   [DEBUG] Navigating to {target_list_url} ...")
            # Changed wait_until to domcontentloaded to prevent infinite timeout from analytics/polling requests
            await page.goto(target_list_url, wait_until="domcontentloaded", timeout=60000)
            
            logger.debug("   [DEBUG] Navigation finished. Waiting for tweet articles to render...")
            await page.wait_for_selector('article[data-testid="tweet"]', timeout=30000)
            logger.debug("   [DEBUG] Tweet articles found on page!")
            
            reached_cutoff = False
            scroll_attempts = 0
            max_scrolls = 50 # Safety valve against infinite loops
            
            while not reached_cutoff and scroll_attempts < max_scrolls:
                logger.debug(f"   [DEBUG] Scroll attempt {scroll_attempts+1}/{max_scrolls}. Evaluating DOM...")
                # Evaluate in browser context for fast DOM parsing
                batch = await page.evaluate('''() => {
                    const articles = document.querySelectorAll('article[data-testid="tweet"]');
                    return Array.from(articles).map(article => {
                        const timeEl = article.querySelector('time');
                        const textEl = article.querySelector('[data-testid="tweetText"]');
                        const userEl = article.querySelector('[data-testid="User-Name"]');
                        const linkEl = article.querySelector('a[href*="/status/"]');
                        
                        return {
                            time: timeEl ? timeEl.getAttribute('datetime') : null,
                            text: textEl ? textEl.innerText : '',
                            author: userEl ? userEl.innerText.replace(/\\n/g, ' ') : 'Unknown',
                            url: linkEl ? linkEl.href : ''
                        };
                    });
                }''')
                
                logger.debug(f"   [DEBUG] Found {len(batch)} tweet elements in DOM.")
                oldest_in_batch = None
                
                for t in batch:
                    if not t['time']:
                        continue
                        
                    # Parse X's ISO time (e.g., 2023-11-20T18:00:00.000Z)
                    dt_str = t['time'].replace('Z', '+00:00')
                    tweet_time = datetime.datetime.fromisoformat(dt_str)
                    
                    if oldest_in_batch is None or tweet_time < oldest_in_batch:
                        oldest_in_batch = tweet_time
                        
                    if tweet_time >= cutoff:
                        tweet_id = t['url'] if t['url'] else f"{t['author']}_{dt_str}"
                        if tweet_id not in tweets_dict and t['text']:
                            tweets_dict[tweet_id] = {
                                "sender": t['author'],
                                "text": t['text'],
                                "url": t['url'],
                                "ts": tweet_time.timestamp()
                            }
                            
                logger.debug(f"   [DEBUG] Oldest tweet in batch: {oldest_in_batch}. Cutoff is {cutoff}.")
                
                if oldest_in_batch and oldest_in_batch < cutoff:
                    logger.debug("   [DEBUG] Reached cutoff! Stopping pagination.")
                    reached_cutoff = True
                
                if not reached_cutoff:
                    logger.debug("   [DEBUG] Scrolling down for more tweets...")
                    # Scroll down 3000px to trigger Twitter's virtualized list rendering
                    await page.evaluate("window.scrollBy(0, 3000)")
                    await page.wait_for_timeout(2500)
                    scroll_attempts += 1
                    
        except Exception as e:
            print(f"   ❌ X List Playwright Error: {e}")
        finally:
            await context.close()
            
    raw_tweets = list(tweets_dict.values())
    print(f"   Scraped {len(raw_tweets)} raw tweets. Pushing to Gemini for pre-filtering...")
    
    if not raw_tweets:
        return []
        
    # --- GEMINI FILTERING PHASE ---
    try:
        client = get_client()
        from genai_client import get_best_model
        preferred_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        model_name = get_best_model(client, preferred_model)
        
        response = client.models.generate_content(
            model=model_name,
            config={
                "system_instruction": PROMPT_X_FILTER_SYSTEM,
                "response_mime_type": "application/json" # Forces strictly formatted JSON output
            },
            contents=[json.dumps(raw_tweets, indent=2), "Filter these tweets based on relevance and return the JSON array."]
        )
        
        filtered_tweets = json.loads(response.text)
        
        # Format into the standard Chief of Staff interface schema
        final_messages = []
        for t in filtered_tweets:
            final_messages.append({
                "platform": "X (List)",
                "channel": "Curated Alpha",
                "sender": t.get("sender", "Unknown"),
                "text": f"{t.get('text', '')}\nURL: {t.get('url', '')}\n\n[Relevance]: {t.get('relevance', '')}",
                "ts": t.get("ts", datetime.datetime.now().timestamp())
            })
            
        print(f"   Filtered down to {len(final_messages)} highly relevant signals.")
        return final_messages

    except Exception as e:
        print(f"   Gemini Filtering Error: {e}")
        return []
