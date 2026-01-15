# Batch version of https://gitingest.com/
import os
import argparse
import subprocess
import time
from git import Repo
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from genai_client import get_client

# Client initialization (picks up GEMINI_API_KEY from environment)
client = get_client()
console = Console()

system_instruction = (
    "Act as my collaborative teammate and partner. Your tone must be peaceful, joyful, "
    "smooth, resonant, intelligent, positive, motivational, and relaxed. "
    "State information directly and affirmatively, avoiding corrective structures. "
    "Define acronyms and esoteric terminology. Use American spelling and present "
    "information in structured paragraphs."
)

task_prompt = (
    "TASK: Identify and summarize the latest changes in the provided repository text.\n\n"
    "STRUCTURE:\n"
    "1. A one-paragraph executive summary of recent code shifts and architectural updates.\n"
    "2. A second paragraph detailing technical breakthroughs and key improvements.\n\n"
    "CONSTRAINTS:\n"
    "- Explicitly connect technical progress to the long-term goals of the project.\n"
    "- Highlight specific performance improvements, refactors, or new features.\n"
    "- Maintain the requested persona and tone."
)

# Command to run repo-to-text. Adjust if necessary.
# Added ignore patterns to reduce payload size
IGNORE_PATTERNS = (
    "*.png *.jpg *.jpeg *.gif *.svg *.mp4 *.mov *.avi *.mp3 *.wav "
    "*.pdf *.zip *.tar *.gz *.pyc *.pkl *.bin *.exe *.dll *.so *.dylib "
    "node_modules .git package-lock.json yarn.lock pnpm-lock.yaml uv.lock"
)
REPO_TO_TEXT_CMD = f"repo-to-text . --ignore-patterns {IGNORE_PATTERNS}"

# Max characters for Gemini payload (approx 250k tokens, or 800k if dense)
MAX_CHARS = 1_000_000

def analyze_repos():
    parser = argparse.ArgumentParser(description="Generate summaries for multiple repositories.")
    parser.add_argument("path", help="Directory containing the repositories.")
    args = parser.parse_args()

    base_dir = args.path
    if not os.path.isdir(base_dir):
        console.print(f"[bold red]Error:[/bold red] Directory not found: {base_dir}")
        return

    # Output file
    output_file_path = os.path.join(base_dir, "all_recaps.md")
    
    console.print(f"[bold blue]Starting analysis on repositories in:[/bold blue] {base_dir}")
    console.print(f"[bold blue]Output will be saved to:[/bold blue] {output_file_path}")

    summaries = []
    repo_list = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
    
    if not repo_list:
        console.print("[yellow]No repositories found in the specified directory.[/yellow]")
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        overall_task = progress.add_task("[green]Processing Repositories...", total=len(repo_list))

        for repo_name in repo_list:
            repo_path = os.path.join(base_dir, repo_name)
            progress.update(overall_task, description=f"[green]Processing {repo_name}...")
            
            try:
                # 1. Pull latest changes
                try:
                    repo = Repo(repo_path)
                    origin = repo.remote('origin')
                    # console.print(f"  [PULL] Pulling changes...") # Too noisy with progress bar
                    origin.pull()
                except Exception as e:
                    # console.print(f"  [WARNING] Git pull failed: {e}")
                    pass # Keep UI clean

                # 2. Run repo-to-text
                # console.print(f"  [TEXT] Running repo-to-text...")
                subprocess.run(REPO_TO_TEXT_CMD, shell=True, check=True, cwd=repo_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                # 3. Find the latest repo-to-text file
                txt_files = [f for f in os.listdir(repo_path) if f.startswith("repo-to-text_") and f.endswith(".txt")]
                if not txt_files:
                    # console.print(f"  [SKIP] No repo-to-text output found in {repo_name}")
                    progress.advance(overall_task)
                    continue
                
                latest_file = max(txt_files, key=lambda f: os.path.getctime(os.path.join(repo_path, f)))
                latest_file_path = os.path.join(repo_path, latest_file)

                # 4. Generate Summary
                # console.print(f"  [AI] Generating summary for {latest_file}...")
                with open(latest_file_path, 'r') as f:
                    repo_content = f.read()

                # Truncate content if too large
                if len(repo_content) > MAX_CHARS:
                    repo_content = repo_content[:MAX_CHARS] + "\n\n[TRUNCATED DUE TO SIZE LIMIT]"
                    # console.print(f"  [INFO] Truncated {repo_name} content to {MAX_CHARS} chars.")

                # Use a separate spinner for the AI generation part if we want detailed feedback, 
                # but inside a progress loop it's tricky. 
                # Instead, we can update the description.
                progress.update(overall_task, description=f"[cyan]Generating AI Summary for {repo_name}...")
                
                # Retry logic for rate limits
                max_retries = 3
                retry_delay = 40 # seconds
                response_text = ""

                for attempt in range(max_retries):
                    try:
                        response = client.models.generate_content(
                            model="gemini-2.0-flash",
                            config={"system_instruction": system_instruction},
                            contents=[task_prompt, repo_content]
                        )
                        response_text = response.text
                        break # Success, exit loop
                    except Exception as e:
                        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                            if attempt < max_retries - 1:
                                progress.update(overall_task, description=f"[yellow]Rate limit hit for {repo_name}. Retrying in {retry_delay}s... ({attempt+1}/{max_retries})")
                                time.sleep(retry_delay)
                            else:
                                raise e # Re-raise after max retries
                        else:
                            raise e # Re-raise other errors immediately
                
                summaries.append(f"# {repo_name}\n\n{response_text}\n\n---\n")
                # console.print(f"  [DONE] Summary generated.")

            except Exception as e:
                console.print(f"[bold red]Failed to process {repo_name}: {e}[/bold red]")
            
            progress.advance(overall_task)

    # Write all summaries to file
    if summaries:
        with open(output_file_path, 'w') as f:
            f.write(f"# Repository Recaps\nGenerated: {time.ctime()}\n\n")
            f.writelines(summaries)
        console.print(f"\n[bold green]✅ All summaries written to {output_file_path}[/bold green]")
    else:
        console.print("\n[yellow]No summaries were generated.[/yellow]")

if __name__ == "__main__":
    analyze_repos()
