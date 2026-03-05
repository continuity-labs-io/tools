import os
import datetime
from typing import List, Dict
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

def fetch_gmail() -> List[Dict]:
    print("🔵 Fetching Gmail...")
    SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
    creds = None
    
    # Pointing to the secrets directory for tokens
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    token_path = os.path.join(base_dir, 'secrets', 'token.json')
    creds_path = os.path.join(base_dir, 'secrets', 'credentials.json')

    # Inner function to handle the auth flow
    def authenticate():
        flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
        new_creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as token:
            token.write(new_creds.to_json())
        return new_creds

    # 1. Try to load existing token
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception:
            print("   ⚠️ Token file corrupt. Re-authenticating...")
            creds = authenticate()

    # 2. Check validity and refresh if needed
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"   ⚠️ Token expired/revoked ({e}). Deleting and re-authenticating...")
                if os.path.exists(token_path):
                    os.remove(token_path)
                creds = authenticate()
        else:
            if not os.path.exists(creds_path):
                print("   ❌ Skipping Gmail (No secrets/credentials.json found)")
                return []
            creds = authenticate()

    # 3. Fetch Messages
    try:
        service = build('gmail', 'v1', credentials=creds)
        
        yesterday = datetime.datetime.now() - datetime.timedelta(days=1)
        query_date = yesterday.strftime("%Y/%m/%d")
        query = f'after:{query_date} -category:promotions -category:social'

        results = service.users().messages().list(userId='me', q=query).execute()
        messages = results.get('messages', [])
        
        email_data = []
        for msg in messages[:15]: 
            msg_detail = service.users().messages().get(userId='me', id=msg['id']).execute()
            headers = msg_detail['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), "No Subject")
            sender = next((h['value'] for h in headers if h['name'] == 'From'), "Unknown")
            snippet = msg_detail.get('snippet', '')
            
            email_data.append({
                "platform": "Gmail",
                "sender": sender,
                "subject": subject,
                "text": snippet,
                "ts": datetime.datetime.now().timestamp()
            })

        print(f"   Found {len(email_data)} emails.")
        return email_data

    except Exception as e:
        print(f"   ❌ Gmail API Error: {e}")
        return []
