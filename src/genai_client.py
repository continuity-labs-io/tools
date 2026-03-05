import os
from google import genai
from dotenv import load_dotenv

def get_client() -> genai.Client:
    # Resolve the absolute path to the repository root
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Ensure environment variables are loaded from the root .env file
    # This makes it safe to run from tests or from the main entrypoint
    env_path = os.path.join(current_dir, '..', 'secrets', '.env')
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path, override=True)
    
    api_key = os.getenv("GEMINI_API_KEY")
    
    if not api_key:
        raise ValueError("GEMINI_API_KEY is missing. Please verify the .env file.")
        
    return genai.Client(api_key=api_key)