import sys
import requests
from google import genai
import os

# Client initialization (Now picks up GEMINI_API_KEY from environment)
client = genai.Client()

system_instruction = (
    "Act as my collaborative teammate and partner. Your tone must be peaceful, joyful, "
    "smooth, resonant, intelligent, positive, motivational, and relaxed. "
    "Avoid corrective sentence structures. Define all acronyms and esoteric terms. "
    "Use American spelling and present information in paragraphs."
)

# Create a detailed task description
task_prompt = (
    "TASK: Summarize the provided podcast audio file.\n\n"
    "STRUCTURE:\n"
    "1. A one-paragraph executive summary stating information affirmatively.\n"
    "2. A second paragraph detailing technical breakthroughs or specific biohacking protocols.\n\n"
    "CONSTRAINTS:\n"
    "- Identify specific blood markers or dosages mentioned.\n"
    "- Reference any mention of 'whole brain emulation' or 'topological ML'.\n"
    "- Use only information directly from the audio."
)

def automate_summary():
    # Read the title and URL piped from the human_upgrade function
    input_data = sys.stdin.read().strip().split('\n')
    
    if len(input_data) < 2:
        print("Error: Expected Title and URL from input.")
        return

    title = input_data[0]
    url = input_data[1]
    filename = "temp_podcast.mp3"

    # Download
    print(f"Downloading: {title}...")
    r = requests.get(url)
    with open(filename, 'wb') as f:
        f.write(r.content)

    try:
        # Upload and Summarize
        print("Uploading and generating summary...")
        uploaded_file = client.files.upload(file=filename)

        model="gemini-2.5-flash-lite", # High-speed choice
        model = "gemini-3-pro-preview"
        response = client.models.generate_content(
            model=model,
            config={"system_instruction": system_instruction},
            contents=[task_prompt, uploaded_file]
        )
        print(f"\n--- Summary for {title} ---\n{response.text}")

    finally:
        # Cleanup
        if os.path.exists(filename): os.remove(filename)
        if 'uploaded_file' in locals(): client.files.delete(name=uploaded_file.name)

if __name__ == "__main__":
    automate_summary()
