# Tools Repository

This repository contains a collection of Python scripts for personal productivity and automation, powered by Google's Gemini models.

## Prerequisites

- Python 3.10+
- A Google Cloud Project with the Gemini API enabled.
- A `GEMINI_API_KEY`.

## Installation

1.  Clone the repository:
    ```bash
    git clone <your-repo-url>
    cd tools
    ```

2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
    *(Note: If `requirements.txt` doesn't exist, install the common libraries manually: `google-genai`, `python-dotenv`, `rich`, `slack_sdk`, `telethon`, `google-auth`, `google-auth-oauthlib`, `google-api-python-client`, `gitpython`, `requests`)*

## Global Setup

1.  **Environment Variables**:
    Create a `.env` file in the root of the `tools` directory (or ensure your environment has these set):
    ```bash
    GEMINI_API_KEY="your_api_key_here"
    SLACK_TOKEN_LBF="your_slack_token"   # Optional, for Chief of Staff
    SLACK_TOKEN_12SF="your_slack_token"  # Optional, for Chief of Staff
    TELEGRAM_API_ID="your_id"            # Optional, for Chief of Staff
    TELEGRAM_API_HASH="your_hash"        # Optional, for Chief of Staff
    ```

2.  **Shared Client**:
    The scripts use `src/genai_client.py` to initialize the Gemini client and load environment variables.

### Setup: Adding a New Slack Workspace

Don't manually configure scopes. Use the **App Manifest** to configure a new workspace in <60 seconds.

#### 1. Create the App
1. Go to [api.slack.com/apps](https://api.slack.com/apps).
2. Click **Create New App** → Select **From an app manifest**.
3. Select the workspace you want to add.
4. Click **Next** and ensure the tab is set to **YAML**.
5. Paste the [Manifest Configuration](#manifest-configuration) below (overwrite everything).
6. Click **Next** → **Create**.

#### 2. Install & Get Token
1. Click **"Install to Workspace"** (green button).
2. Click **Allow**.
3. Copy the **User OAuth Token** (starts with `xoxp-...`).

#### 3. Update Environment
1. Add the token to your local `.env` file:
   ```bash
   ```bash
   SLACK_TOKEN_NEW_WORKSPACE=xoxp-your-token-here
   ```
   *Note: The script automatically loads any environment variable starting with `SLACK_TOKEN_` as a workspace token.*

#### Manifest Configuration
(See `template/slack.yml` for the full YAML configuration)

## Scripts

### 1. Chief of Staff (`src/chief_of_staff.py`)

Acts as an executive assistant, filtering messages from Gmail (and optionally Slack/Telegram) and generating a prioritized daily briefing.

**Setup:**
-   **Credentials**: Place your Google OAuth `credentials.json` and `token.json` in `~/.config/chief_of_staff/`.
    ```bash
    mkdir -p ~/.config/chief_of_staff
    cp path/to/credentials.json ~/.config/chief_of_staff/
    ```
    *(The script will generate `token.json` on first run if it doesn't exist, requiring browser authentication).*

**Usage:**
```bash
python src/chief_of_staff.py
```
*Tip: Alias this command to `cos` for easy access.*

**Options:**
- `--sources`: Specify which data sources to fetch (default: all).
  ```bash
  python src/chief_of_staff.py --sources gmail
  python src/chief_of_staff.py --sources slack telegram
  ```

### 2. Repository Recap (`src/recap_repos.py`)

Generates summaries for multiple git repositories in a given directory. It pulls the latest changes, converts the repo to text (using `repo-to-text`), and uses Gemini to generate an executive summary of changes and technical breakthroughs.

**Prerequisites:**
-   `repo-to-text` tool must be installed and available in your PATH.
-   `git` must be installed.

**Usage:**
```bash
python src/recap_repos.py <path_to_directory_containing_repos>
```
Example:
```bash
python src/recap_repos.py ~/gh/active
```

### 3. Podcast Summarizer (`src/podcast_summarizer.py`)

Downloads a podcast audio file from a URL, uploads it to Gemini, and generates a structured summary including biohacking protocols and technical details.

**Usage:**
The script expects the **Title** and **URL** to be piped into standard input (stdin), separated by a newline.

```bash
echo -e "Podcast Title\nhttp://example.com/podcast.mp3" | python src/podcast_summarizer.py
```
