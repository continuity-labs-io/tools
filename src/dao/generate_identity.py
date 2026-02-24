#!/usr/bin/env python3
import secrets
from eth_account import Account

# ENABLE "Offline Mode" (We aren't connecting to any RPC)
Account.enable_unaudited_hdwallet_features()

def generate_maker_identity():
    print(f"\n{'='*60}")
    print(f"🔐  GENERATE IDENTITY (OFFLINE MODE)")
    print(f"{'='*60}")
    
    # 1. The Entropy (The "God" Number)
    # We grab 32 random bytes from the OS (os.urandom)
    private_key = "0x" + secrets.token_hex(32)
    
    # 2. The Math (Deriving the Public Face)
    # This transforms the private number into the public address
    acct = Account.from_key(private_key)
    
    print(f"TYPE:   Ethereum / Base Keypair")
    print(f"------------------------------------------------------------")
    print(f"🔑 PRIVATE KEY (The 'Nuclear Waste' - NEVER SHARE):")
    print(f"{private_key}")
    print(f"------------------------------------------------------------")
    print(f"Cd PUBLIC ADDRESS (The 'Mailbox' - SHARE FREELY):")
    print(f"{acct.address}")
    print(f"{'='*60}\n")
    print("NOTE: This was generated locally. It does not exist on the chain")
    print("until you send money to it. For now, it is just a number.\n")

if __name__ == "__main__":
    # You might need to install this lib: pip install eth-account
    try:
        generate_maker_identity()
    except ImportError:
        print("❌ Missing Library. Run: pip install eth-account")


