import os
from google import genai
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

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

def get_best_model(client: genai.Client, preferred_model: str) -> str:
    """Finds the best available model, falling back to previews or defaults if the preferred is missing."""
    available_models = [m.name.replace("models/", "") for m in client.models.list()]
    
    if preferred_model in available_models:
        return preferred_model
        
    # Look for a preview or variation of the same model
    for am in available_models:
        if am.startswith(preferred_model):
            logger.debug(f"   [WARN] Exact model '{preferred_model}' not found. Auto-switching to '{am}'.")
            return am
            
    # Fallback to a stable default
    default = "gemini-3.5-flash"
    if default in available_models:
        logger.debug(f"   [WARN] Model '{preferred_model}' not found. Auto-switching to default '{default}'.")
        return default
        
    # If all else fails, just return the first available model
    if available_models:
        fallback = available_models[0]
        logger.debug(f"   [WARN] Model '{preferred_model}' not found. Auto-switching to '{fallback}'.")
        return fallback
        
    return preferred_model