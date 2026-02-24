#!/usr/bin/env python3
import requests
import sys
import time

# --- CONFIGURATION ---
BASE_URL = "https://api.coingecko.com/api/v3"
CATEGORY = "governance"

def resolve_id(query):
    """
    Asks CoinGecko: 'I have this symbol/name, what is the real ID?'
    Returns the ID of the highest-ranked match.
    """
    try:
        # Use the Search endpoint to find matches
        url = f"{BASE_URL}/search"
        params = {"query": query}
        
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        
        coins = data.get('coins', [])
        
        if not coins:
            return None
            
        # LOGIC: Find the best match
        # 1. Exact Symbol Match? (e.g. 'MKR')
        # 2. Highest Market Cap Rank (The 'Real' one)
        
        best_match = None
        
        # Sort results by rank (null ranks go to bottom)
        # We use 999999 as a fallback for unranked coins
        coins.sort(key=lambda x: x.get('market_cap_rank') or 999999)
        
        # Return the #1 result after sorting
        if coins:
            best_match = coins[0]
            return best_match['id']
            
    except Exception:
        return None
    
    return None

def list_daos():
    """Fetches top DAOs by market cap."""
    print(f"Fetching top tokens in category: '{CATEGORY}'...")
    
    try:
        url = f"{BASE_URL}/coins/markets"
        params = {
            "vs_currency": "usd",
            "category": CATEGORY,
            "order": "market_cap_desc",
            "per_page": 20,
            "page": 1,
            "sparkline": "false"
        }
        
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        print(f"{'='*60}")
        print(f"{'RANK':<5} {'NAME':<25} {'SYMBOL':<10} {'PRICE':<12} {'MARKET CAP'}")
        print(f"{'='*60}")

        for coin in data:
            rank = coin.get('market_cap_rank', 'N/A')
            name = coin.get('name', 'Unknown')[:24]
            symbol = coin.get('symbol', '???').upper()
            price = coin.get('current_price', 0)
            mcap = coin.get('market_cap', 0)

            print(f"{str(rank):<5} {name:<25} {symbol:<10} ${price:<11,.2f} ${mcap:,.0f}")
        
        print(f"{'='*60}")

    except Exception as e:
        print(f"Error fetching list: {e}")

def get_dao_report(query):
    """Fetches a detailed report for a specific DAO."""
    
    # 1. RESOLVE THE ID DYNAMICALLY
    print(f"🔎 Searching for '{query}'...")
    dao_id = resolve_id(query)
    
    if not dao_id:
        print(f"❌ Error: Could not find any DAO matching '{query}'.")
        return

    print(f"✅ Found ID: '{dao_id}'. Fetching report...")

    # 2. GET THE DATA
    try:
        url = f"{BASE_URL}/coins/{dao_id}"
        params = {
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "true", 
            "developer_data": "true"
        }
        
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

        # Parse Data
        name = data.get('name')
        symbol = data.get('symbol').upper()
        price = data['market_data']['current_price'].get('usd', 0)
        mcap = data['market_data']['market_cap'].get('usd', 0)
        dev_score = data.get('developer_score', 0)
        
        # Clean Description
        raw_desc = data.get('description', {}).get('en', '')
        desc = raw_desc.replace('\r\n', ' ').replace('<a href="', '').replace('">', ' ')[:300]

        print(f"\n{'='*60}")
        print(f"REPORT: {name} ({symbol})")
        print(f"{'='*60}")
        print(f"Price:        ${price:,.2f}")
        print(f"Market Cap:   ${mcap:,.0f}")
        print(f"Dev Score:    {dev_score}/100")
        print(f"{'-'*60}")
        print(f"Summary: {desc}...")
        print(f"{'='*60}\n")

    except Exception as e:
        print(f"API Error: {e}")

# --- MAIN ---
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: dao [list | <symbol>]")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "list":
        list_daos()
    else:
        get_dao_report(command)

