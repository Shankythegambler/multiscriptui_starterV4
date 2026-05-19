import os
import tempfile
from pathlib import Path
import pandas as pd
import requests
from PIL import Image

# --- HARDCODED POPPLER PATH ---
POPPLER_PATH = r"C:\Users\shashank.singh\Desktop\Backup\Python Script\Release-24.08.0-0\poppler-24.08.0\Library\bin"
os.environ["PATH"] += os.pathsep + POPPLER_PATH
# ------------------------------

from core.io_utils import ensure_dir
from core.logging_utils import push_log

DESCRIPTION = "Run OCR on uploaded or locally selected education documents using docTR and optionally send extracted text to Ollama."
BADGES = ["docTR", "Ollama", "Offline-first", "Folder Support"]
ASSISTANT_HINT = "Use local paths, folder paths, or uploads. Images are cleaned through PIL before OCR so docTR can read them more reliably."
SUPPORTS_LOCAL_PATHS = True

PARAMS = [
    {"name": "ocr_files", "type": "files", "label": "Education documents or folders"},
    {"name": "ocr_engine", "type": "select", "label": "OCR engine", "options": ["docTR", "None"], "default": "docTR"},
    {"name": "use_ollama", "type": "select", "label": "Use Ollama after OCR", "options": ["No", "Yes"], "default": "Yes"},
    {"name": "ollama_url", "type": "text", "label": "Ollama URL", "default": "http://localhost:11434"},
    {"name": "ollama_model", "type": "text", "label": "Ollama model", "default": "llama3.1"},
]

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

def _check_cv2_headless():
    try:
        import cv2  # noqa
        return True, ""
    except Exception as e:
        return False, (
            "OpenCV import failed. Install headless OpenCV instead of regular OpenCV. "
            f"Underlying error: {e}"
        )

def _prepare_image_for_doctr(file_path: str) -> str:
    if not os.path.isfile(file_path):
        raise RuntimeError(f"File not found: {file_path}")

    try:
        with Image.open(file_path) as img:
            img.load()
            if img.mode != "RGB":
                img = img.convert("RGB")

            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmp_path = tmp.name
            tmp.close()

            img.save(tmp_path, format="PNG")
            return tmp_path
    except Exception as e:
        raise RuntimeError(f"Could not prepare image for OCR: {e}")

def _run_doctr(file_path: str):
    ok, cv2_msg = _check_cv2_headless()
    if not ok:
        raise RuntimeError(cv2_msg + " Please fix OpenCV in the active environment, then rerun OCR.")

    try:
        from doctr.io import DocumentFile
        from doctr.models import ocr_predictor
    except Exception as e:
        raise RuntimeError(f"docTR is not installed or not available: {e}")

    if not os.path.isfile(file_path):
        raise RuntimeError(f"Input file not found: {file_path}")

    model = ocr_predictor(pretrained=True)
    ext = os.path.splitext(file_path)[1].lower()

    temp_cleanup = None
    try:
        if ext == ".pdf":
            doc = DocumentFile.from_pdf(file_path)
        elif ext in IMAGE_EXTS:
            cleaned_image = _prepare_image_for_doctr(file_path)
            temp_cleanup = cleaned_image
            doc = DocumentFile.from_images(cleaned_image)
        else:
            raise RuntimeError(f"Unsupported OCR file type: {ext}")

        result = model(doc)
        export = result.export()

        lines = []
        for page in export.get("pages", []):
            for block in page.get("blocks", []):
                for line in block.get("lines", []):
                    words = [w.get("value", "") for w in line.get("words", []) if w.get("value", "")]
                    joined = " ".join(words).strip()
                    if joined:
                        lines.append(joined)

        text = "\n".join(lines).strip()
        return text, export

    except Exception as e:
        raise RuntimeError(f"docTR OCR failed: {e}")
    finally:
        if temp_cleanup and os.path.isfile(temp_cleanup):
            try:
                os.remove(temp_cleanup)
            except Exception:
                pass

def _ask_ollama(ollama_url: str, ollama_model: str, text: str):
    prompt = f"""
You are extracting education-document details from OCR text.

Return a concise structured response with these fields when available:
- candidate_name
- institution_name
- degree
- course
- roll_number
- registration_number
- passing_year
- marks_or_cgpa
- document_type
- remarks

OCR text:
{text[:12000]}
""".strip()

    url = ollama_url.rstrip("/") + "/api/generate"
    payload = {
        "model": ollama_model,
        "prompt": prompt,
        "stream": False,
    }

    response = requests.post(url, json=payload, timeout=180)
    response.raise_for_status()
    data = response.json()
    return data.get("response", "").strip()

def run(inputpath, outputpath, kwargs, log_queue=None):
    log_queue = log_queue or []
    ensure_dir(outputpath)

    raw_files = kwargs.get("ocr_files", [])
    ocr_engine = kwargs.get("ocr_engine", "docTR")
    use_ollama = kwargs.get("use_ollama", "Yes")
    ollama_url = kwargs.get("ollama_url", "").strip()
    ollama_model = kwargs.get("ollama_model", "").strip()

    # --- NEW: Folder Expansion Logic ---
    files = []
    for path in raw_files:
        if os.path.isdir(path):
            push_log(log_queue, "INFO", f"Scanning directory: {path}")
            for root, _, filenames in os.walk(path):
                for fname in filenames:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in IMAGE_EXTS or ext == ".pdf":
                        files.append(os.path.join(root, fname))
        elif os.path.isfile(path):
            files.append(path)
        else:
            push_log(log_queue, "WARNING", f"Path not found or invalid: {path}")

    total_files = len(files)
    if total_files == 0:
        raise ValueError("Please provide at least one valid document file or a folder containing documents.")

    all_rows = []
    output_files = []

    # Added enumeration here to track progress!
    for idx, file_path in enumerate(files, start=1):
        base_name = Path(file_path).name
        # Progress indicator added to the log
        push_log(log_queue, "INFO", f"[{idx}/{total_files}] Processing OCR for {base_name}")

        try:
            if ocr_engine == "docTR":
                text, export = _run_doctr(file_path)
            else:
                text, export = "", {}

            txt_path = os.path.join(outputpath, f"{Path(file_path).stem}_ocr.txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(text)
            output_files.append(txt_path)

            ollama_result = ""
            if use_ollama == "Yes" and ollama_url and ollama_model and text.strip():
                try:
                    push_log(log_queue, "INFO", f"[{idx}/{total_files}] Sending OCR text of {base_name} to Ollama")
                    ollama_result = _ask_ollama(ollama_url, ollama_model, text)
                    ollama_path = os.path.join(outputpath, f"{Path(file_path).stem}_ollama_summary.txt")
                    with open(ollama_path, "w", encoding="utf-8") as f:
                        f.write(ollama_result)
                    output_files.append(ollama_path)
                except Exception as oe:
                    push_log(log_queue, "ERROR", f"[{idx}/{total_files}] Ollama failed for {base_name}: {oe}")
                    ollama_result = f"Ollama failed: {oe}"

            all_rows.append({
                "file_name": base_name,
                "ocr_engine": ocr_engine,
                "status": "Completed",
                "text_length": len(text),
                "use_ollama": use_ollama,
                "ollama_url": ollama_url,
                "ollama_model": ollama_model,
                "ollama_result_preview": ollama_result[:500],
                "output_text_file": txt_path,
            })

        except Exception as e:
            push_log(log_queue, "ERROR", f"[{idx}/{total_files}] OCR failed for {base_name}: {e}")
            all_rows.append({
                "file_name": base_name,
                "ocr_engine": ocr_engine,
                "status": f"Failed: {e}",
                "text_length": 0,
                "use_ollama": use_ollama,
                "ollama_url": ollama_url,
                "ollama_model": ollama_model,
                "ollama_result_preview": "",
                "output_text_file": "",
            })

    report_df = pd.DataFrame(all_rows)
    report_path = os.path.join(outputpath, "education_ocr_report.xlsx")
    report_df.to_excel(report_path, index=False)
    
    # We generate the text files on the disk, but we ONLY show the Excel/CSV report on the UI
    push_log(log_queue, "SUCCESS", f"OCR completed for {total_files} files.")
    return {"output_files": [report_path]}