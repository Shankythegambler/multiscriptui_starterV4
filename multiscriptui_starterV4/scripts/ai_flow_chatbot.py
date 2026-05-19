import os
import requests

from core.io_utils import ensure_dir
from core.logging_utils import push_log


DESCRIPTION = "Ask an Ollama-powered assistant what your current toolkit can do, which tool to use, and how to combine tools."
BADGES = ["Ollama", "Tool guidance", "Workflow assistant"]
ASSISTANT_HINT = "Ask things like: What can my current flow do? Which tool should I use for university matching? How should I process employment documents?"
SUPPORTS_LOCAL_PATHS = True

PARAMS = [
    {"name": "question", "type": "textarea", "label": "Your question"},
    {"name": "ollama_url", "type": "text", "label": "Ollama URL", "default": "http://localhost:11434"},
    {"name": "ollama_model", "type": "text", "label": "Ollama model", "default": "llama3.1"},
    {"name": "extra_context", "type": "textarea", "label": "Optional extra context", "default": ""},
]


TOOL_KNOWLEDGE = """
You are assisting a user who uses a local offline Streamlit-based data utility suite.

Current available tools and flows:

1. Lookup Engine
- Match input records against one or more lookup files
- Supports matched, unmatched, and consolidated outputs
- Adds lookup_source_file, match_status, reason
- Works for exact data matching across CSV/XLSX

2. Excel / CSV Merger
- Merge multiple CSV or Excel files
- Add source tracking when needed

3. Excel Multi-Search
- Search one or more terms across Excel files in a folder
- Capture matching rows with file and sheet info

4. Name Matcher
- Compare two name columns
- Generate similarity score and notes
- Good for fuzzy name matching and review buckets

5. File Zipper
- Compress files into zip packages

6. Bulk File Downloader
- Read URLs from file and download in batch

7. Data Cleaning Utility
- Clean columns, trim spaces, standardize strings, remove junk rows

8. Name Cleaner & Categorizer
- Normalize names and prepare them for matching or classification

9. Advanced Status Profiler
- Summarize selected columns
- Blank/null analysis
- Distinct counts
- Top values
- Narrative summary
- Optional group-by cross-analysis

10. Base64 to File Extractor
- Decode Base64 content
- Spreadsheet mode and local TXT folder scan mode

11. PDF Folder Merger
- For a local root folder, create one merged PDF for each child folder
- Supports PDF, image, and Excel inputs

12. Mixed File PDF Merger
- Merge mixed PDFs, images, and Excel files into a single merged PDF flow

13. PDF to Excel
- Extract tables or text from PDFs
- Create a combined Excel output

14. PDF to JPG
- Convert PDF pages to JPG
- Supports Poppler path if needed

15. Education Documents OCR
- OCR for education documents using docTR
- Optional Ollama post-processing

16. Employment Documents OCR
- OCR for employment-related documents
- Extract fields like Name, Employee ID, Company Name, DOJ, DOL, Designation, CTC, Reason for Leaving, Document Type
- Uses docTR + smart rules + optional Ollama extraction

Important behavior:
- Recommend the best tool or best sequence of tools
- If a task needs multiple tools, explain the sequence clearly
- Keep the answer practical and oriented to the user's offline workflow
- Do not mention cloud deployment unless asked
- Assume the user is running the tools locally
""".strip()


def ask_ollama(ollama_url: str, ollama_model: str, question: str, extra_context: str) -> str:
    prompt = f"""
You are an AI workflow assistant for a local data-processing toolkit.

Use the toolkit knowledge below to answer the user's question.
Be practical, direct, and suggest which tool or sequence of tools should be used.

Toolkit knowledge:
{TOOL_KNOWLEDGE}

Extra user context:
{extra_context}

User question:
{question}
""".strip()

    url = ollama_url.rstrip("/") + "/api/generate"
    payload = {
        "model": ollama_model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 700
        }
    }

    response = requests.post(url, json=payload, timeout=180)
    response.raise_for_status()
    data = response.json()
    return data.get("response", "").strip()


def run(inputpath, outputpath, kwargs, log_queue=None):
    log_queue = log_queue or []
    ensure_dir(outputpath)

    question = str(kwargs.get("question", "")).strip()
    ollama_url = str(kwargs.get("ollama_url", "http://localhost:11434")).strip()
    ollama_model = str(kwargs.get("ollama_model", "llama3.1")).strip()
    extra_context = str(kwargs.get("extra_context", "")).strip()

    if not question:
        raise ValueError("Please enter a question.")

    push_log(log_queue, "INFO", f"Sending question to Ollama model: {ollama_model}")
    answer = ask_ollama(ollama_url, ollama_model, question, extra_context)

    output_path = os.path.join(outputpath, "ai_flow_chatbot_answer.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(answer)

    push_log(log_queue, "SUCCESS", "Chatbot response generated.")
    return {"output_files": [output_path]}