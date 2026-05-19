import os
import time
import json
import urllib.parse
import feedparser
import requests
import datetime
from typing import List, Dict

# genai_client is in sys.path due to main.py
from genai_client import get_client

OUTPUT_DIR = os.path.expanduser("~/Downloads/chief_of_staff")
MODEL_NAME = "gemini-3-pro-preview"

RESEARCH_DRAGNET = {
    "math": [
        "Continuous Normalizing Flows", 
        "Neural SDE", 
        "Equivariant Graph Neural Network",
        "EGNN",
        "Amortized inference"
    ],
    "biology": [
        "Waddington landscape", 
        "epigenetic memory", 
        "spatial transcriptomics", 
        "multicellular state",
        "tissue topology"
    ],
    "physics": [
        "Ising Hamiltonian", 
        "non-equilibrium thermodynamics", 
        "Langevin dynamics", 
        "simulated bifurcation",
        "cellular phase transition"
    ]
}

PROMPT_ARXIV_SCORING_SYSTEM = """
You are the Lead Architect of Continuum. Your goal is to evaluate the provided research paper against a specific Weighted Keyword Matrix and determine its relevance to building a civilization-scale biological physics engine.

Continuum is focused on:
1. Building the Amortized Neural Compiler to translate biological models into analog computable primitives.
2. Operating strictly within the Biological Interfacing Zone (timescales of milliseconds to minutes).
3. Utilizing continuous non-equilibrium thermodynamics to model Waddington epigenetic landscapes.
4. Discovering new layer-appropriate observability paradigms for multicellular spatial arrays and continuous boundary flux.

You must output a strictly valid JSON object. No markdown formatting blocks around it, just raw JSON.
Format:
{
  "relevance_score": [0-100 integer],
  "continuum_connection": "[1-2 sentence explanation of how this maps to the Amortized Neural Compiler or Biological Interfacing Zone]",
  "clinical_viability": "[1 sentence on whether this accelerates the Shortest Path to deterministic biological control and Longevity Escape Velocity]",
  "catch": "[1 sentence on any physical data collection limitations, destructive measurement constraints, or computational bottlenecks]",
  "summary": "[1-2 sentence summary of the core mathematical or biological innovation]"
}

Weighted Matrix for Scoring:
1. Math (Weight: 40%): Neural SDEs, Continuous Normalizing Flows, Equivariant GNNs, Amortized Inference.
2. Biology (Weight: 30%): Waddington landscapes, spatial transcriptomics, tissue topology, multicellular interfaces.
3. Physics (Weight: 30%): Ising Hamiltonians, simulated bifurcation, Langevin dynamics, non-equilibrium thermodynamics.
"""

def fetch_arxiv_papers(top_n=5) -> List[Dict]:
    print("🔵 Fetching ArXiv Research (Deep Mode)...")
    
    keywords = [k for category in RESEARCH_DRAGNET.values() for k in category]
    query = "+OR+".join([urllib.parse.quote(k) for k in keywords])
    
    url = f'http://export.arxiv.org/api/query?search_query=all:{query}&start=0&max_results=5&sortBy=submittedDate&sortOrder=descending'
    
    feed = feedparser.parse(url)
    analyzed_papers = []
    
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    client = get_client()

    for entry in feed.entries[:top_n]:
        print(f"> {entry.title[:50]}...")
        
        pdf_link = None
        for link in entry.links:
            if link.type == 'application/pdf':
                pdf_link = link.href
                break
        
        if not pdf_link:
            pdf_link = entry.link.replace("/abs/", "/pdf/") + ".pdf"
            
        filename = os.path.join(OUTPUT_DIR, f"{entry.id.split('/')[-1]}.pdf")
        try:
            response = requests.get(pdf_link)
            with open(filename, 'wb') as f:
                f.write(response.content)
            
            pdf_file = client.files.upload(file=filename)
            
            while pdf_file.state.name == "PROCESSING":
                time.sleep(2)
                pdf_file = client.files.get(name=pdf_file.name)
                
            if pdf_file.state.name == "FAILED":
                print("      PDF processing failed.")
                continue
                
            response = client.models.generate_content(
                model=MODEL_NAME,
                config={
                    "system_instruction": PROMPT_ARXIV_SCORING_SYSTEM,
                    "response_mime_type": "application/json"
                },
                contents=[pdf_file, "Analyze this paper."]
            )
            
            analysis = json.loads(response.text)
            if isinstance(analysis, list):
                analysis = analysis[0]
                
            analysis['title'] = entry.title
            analysis['link'] = entry.link
            analysis['author'] = entry.author
            analyzed_papers.append(analysis)
            
        except Exception as e:
            print(f"      Failed to process {entry.title}: {e}")
            
    analyzed_papers.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
    
    minscore = 10
    breakthrough_score = 50
    final_messages = []
    for p in analyzed_papers:
        score = p.get('relevance_score', 0)
        if score < minscore:
            continue
            
        signal_prefix = "🚨 BREAKTHROUGH SIGNAL" if score > breakthrough_score else f"{score}% Match"
        
        formatted_text = (
            f"**{signal_prefix}: {p['title']}**\n"
            f"* **Why it matters:** {p.get('continuum_connection', 'N/A')}\n"
            f"* **Clinical Viability:** {p.get('clinical_viability', 'N/A')}\n"
            f"* **The Catch:** {p.get('catch', 'N/A')}\n"
            f"* **Summary:** {p.get('summary', 'N/A')}\n"
            f"* **Link:** {p['link']}"
        )
        
        final_messages.append({
            "platform": "ArXiv",
            "channel": "Research",
            "sender": p['author'],
            "text": formatted_text,
            "ts": datetime.datetime.now().timestamp()
        })
        
    print(f"   Processed {len(final_messages)} relevant papers (out of {len(analyzed_papers)} analyzed).")
    return final_messages
