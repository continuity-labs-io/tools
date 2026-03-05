import os
import sys
from dotenv import load_dotenv
from google import genai
from genai_client import get_client

# Force load the .env file from the repository root
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, '..', 'secrets', '.env')
load_dotenv(dotenv_path=env_path, override=True)

# Initialize the client and test the connection
client = get_client()
response = client.models.generate_content(
    model="gemini-2.5-flash", 
    contents="Respond with exactly two words: Connection successful."
)

print(response.text)