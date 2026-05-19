"""
Registry-compatible Ollama Code Generator
Drop into scripts/ollama_code_generator.py
"""

import os
import re
import textwrap
from datetime import datetime


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_available_models() -> list:
    try:
        import ollama
        result = ollama.list()
        models_raw = result.get("models", []) if isinstance(result, dict) else getattr(result, "models", [])
        names = []
        for m in models_raw:
            if isinstance(m, dict):
                name = m.get("name") or m.get("model") or ""
            else:
                name = getattr(m, "model", None) or getattr(m, "name", None) or ""
            if name:
                names.append(name)
        return names
    except Exception:
        return []


# ── Registry metadata ──────────────────────────────────────────────────────────

DESCRIPTION = (
    "Generate production-ready Python code from plain-English instructions "
    "using a locally running Ollama model (100% offline, no API key needed)."
)

# Build model list at import time so the selectbox is populated
_available_models = _get_available_models() or ["llama3.1:latest"]

PARAMS = [
    {
        "name":    "model_name",
        "type":    "select",
        "label":   "🧠 Ollama Model",
        "options": _available_models,
        "default": _available_models[0],
        "help":    "Models currently available on your local Ollama installation.",
    },
    {
        "name":    "output_type",
        "type":    "select",
        "label":   "📦 Output Type",
        "options": ["Script", "Function", "Class", "Streamlit App"],
        "default": "Script",
        "help":    "What kind of Python artifact should be generated?",
    },
    {
        "name":    "instruction",
        "type":    "textarea",
        "label":   "📝 Describe what you want to build",
        "default": "",
        "help":    (
            "Be as detailed as possible — mention inputs, outputs, libraries, "
            "edge cases, and any existing code this should integrate with."
        ),
    },
    {
        "name":    "context_code",
        "type":    "textarea",
        "label":   "📎 Existing code / context (optional)",
        "default": "",
        "help":    "Paste any existing functions, classes, or imports the generated code should build on.",
    },
]

BADGES = ["🤖 AI", "🐍 Python", "💻 Local LLM"]

ASSISTANT_HINT = (
    "Select your Ollama model from the dropdown, choose an output type, "
    "then describe what Python code you need in detail. "
    "The more context you give, the better the generated code."
)

SUPPORTS_LOCAL_PATHS = False


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_code(text: str) -> str:
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()


def _log(log_queue: list, level: str, message: str):
    log_queue.append({
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "level":     level,
        "message":   message,
    })


# ── Main entry point ───────────────────────────────────────────────────────────

def run(inputs_dir: str, outputs_dir: str, kwargs: dict, log_queue: list) -> dict:
    try:
        import ollama
    except ImportError:
        raise RuntimeError("The 'ollama' package is not installed. Run: pip install ollama")

    model       = (kwargs.get("model_name") or _available_models[0]).strip()
    output_type = (kwargs.get("output_type") or "Script").strip()
    instruction = (kwargs.get("instruction") or "").strip()
    context     = (kwargs.get("context_code") or "").strip()

    if not instruction:
        raise ValueError("Please provide an instruction describing what code to generate.")

    _log(log_queue, "INFO", f"Model: {model}  |  Output type: {output_type}")
    _log(log_queue, "INFO", "Connecting to Ollama…")

    # ── Build prompt ───────────────────────────────────────────────────────────
    mode_hints = {
        "Script":        "Write a standalone Python script (.py file).",
        "Function":      "Write one or more reusable Python functions with full docstrings.",
        "Class":         "Write a well-structured Python class with __init__, methods, and docstrings.",
        "Streamlit App": "Write a complete Streamlit app using st.* components.",
    }

    system_prompt = textwrap.dedent("""
        You are an expert Python developer.
        Respond with clean, well-commented, production-ready Python code.
        Always wrap ALL code in a single ```python ... ``` block.
        Add brief inline comments explaining key steps.
        If external packages are needed, add a comment at the top: # pip install <pkg>
        Do not include any explanation outside the code block.
    """).strip()

    user_msg = f"{mode_hints.get(output_type, mode_hints['Script'])}\n\n"
    if context:
        user_msg += f"Existing code / context:\n```python\n{context}\n```\n\n"
    user_msg += f"Task:\n{instruction}"

    _log(log_queue, "INFO", "Sending request to Ollama (this may take 15–60 s)…")

    # ── Call Ollama ────────────────────────────────────────────────────────────
    try:
        response = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_msg},
            ],
        )
    except Exception as e:
        raise RuntimeError(
            f"Ollama request failed: {e}\n"
            "Make sure 'ollama serve' is running in a terminal."
        )

    # Handle both dict and object response styles
    if isinstance(response, dict):
        raw_text = response["message"]["content"]
    else:
        raw_text = response.message.content

    _log(log_queue, "INFO", f"Received {len(raw_text)} characters from model.")

    clean_code = _extract_code(raw_text)
    _log(log_queue, "INFO", f"Extracted {len(clean_code.splitlines())} lines of code.")

    # ── Save output ────────────────────────────────────────────────────────────
    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_type   = output_type.lower().replace(" ", "_")
    output_path = os.path.join(outputs_dir, f"generated_{safe_type}_{timestamp}.py")

    with open(output_path, "w", encoding="utf-8") as f:
        header = textwrap.dedent(f"""\
            # Generated by Ollama Code Generator
            # Model      : {model}
            # Output type: {output_type}
            # Task       : {instruction[:120]}{'...' if len(instruction) > 120 else ''}
            # Timestamp  : {datetime.now().isoformat(timespec='seconds')}
            # ──────────────────────────────────────────────────────────
        """)
        f.write(header + "\n" + clean_code + "\n")

    _log(log_queue, "INFO", f"Saved → {os.path.basename(output_path)}")
    _log(log_queue, "SUCCESS", "Code generation complete! Download your .py file below.")

    return {"output_files": [output_path]}
