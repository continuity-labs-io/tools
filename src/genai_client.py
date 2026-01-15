import os
from google import genai
from dotenv import load_dotenv

def get_client() -> genai.Client:
    """
    Initializes and returns a Google GenAI Client.
    Loads environment variables from .env file if present.
    """
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        # genai.Client() might look for GEMINI_API_KEY env var automatically, 
        # but explicit check/loading is good practice if we want to enforce it or debug.
        # However, the original script just did client = genai.Client(), which implies 
        # it relies on the library's internal env var lookup or the user having it set.
        # We'll stick to the simplest compatible approach but ensure dotenv is loaded.
        pass
    
    return genai.Client(api_key=api_key)
