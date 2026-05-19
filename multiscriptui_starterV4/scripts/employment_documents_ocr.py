import os
import re
import json
import csv
import time
from typing import List, Dict, Any, Tuple
import pandas as pd
import numpy as np
import cv2
import requests
from PIL import Image

# --- HARDCODED POPPLER PATH ---
POPPLER_PATH = r"C:\Users\shashank.singh\Desktop\Backup\Python Script\Release-24.08.0-0\poppler-24.08.0\Library\bin"
os.environ["PATH"] += os.pathsep + POPPLER_PATH
# ------------------------------

from core.io_utils import ensure_dir
from core.logging_utils import push_log

Image.MAX_IMAGE_PIXELS = None

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None

try:
    from doctr.models import ocr_predictor
except ImportError:
    ocr_predictor = None

try:
    import torch
except ImportError:
    torch = None

DESCRIPTION = "Extract employment details from employment-related documents using docTR, smart rules, and optional Ollama."
BADGES = ["Employment OCR", "docTR", "Ollama", "Structured extraction"]
ASSISTANT_HINT = "Use this for offer letters, appointment letters, relieving letters, experience letters, employment verification letters, salary slips, and related documents."
SUPPORTS_LOCAL_PATHS = True

PARAMS = [
    {"name": "employment_files", "type": "files", "label": "Employment document files"},
    {"name": "preprocess", "type": "select", "label": "Enable OpenCV preprocessing", "options": ["No", "Yes"], "default": "No"},
    {"name": "max_side", "type": "select", "label": "Max image side length", "options": ["1200", "1600", "2000"], "default": "1600"},
    {"name": "keep_raw_ocr", "type": "select", "label": "Keep raw OCR text in JSON output", "options": ["No", "Yes"], "default": "No"},
    {"name": "enable_llm", "type": "select", "label": "Enable Ollama extraction", "options": ["No", "Yes"], "default": "Yes"},
    {"name": "ollama_url", "type": "text", "label": "Ollama URL", "default": "http://localhost:11434"},
    {"name": "ollama_model", "type": "text", "label": "Ollama model", "default": "llama3.1"},
]

SUPPORTED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".pdf"
}

def is_supported_file(filename: str) -> bool:
    return os.path.splitext(filename.lower())[1] in SUPPORTED_EXTENSIONS

def clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()

def pil_to_cv_bgr(img: Image.Image) -> np.ndarray:
    arr = np.array(img.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

def render_pdf_to_images(pdf_path: str, scale: float = 1.5) -> List[Image.Image]:
    if pdfium is None:
        raise ImportError("pypdfium2 is required for PDF support. Install it with: pip install pypdfium2")

    images = []
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            bitmap = page.render(scale=scale)
            pil_image = bitmap.to_pil().convert("RGB")
            images.append(pil_image)
    finally:
        pdf.close()
    return images

def load_images_from_file(file_path: str) -> List[Image.Image]:
    ext = os.path.splitext(file_path.lower())[1]
    if ext == ".pdf":
        return render_pdf_to_images(file_path)
    return [Image.open(file_path).convert("RGB")]

def downscale_image(img: Image.Image, max_side: int = 1600) -> Image.Image:
    w, h = img.size
    longest = max(w, h)
    if longest <= max_side:
        return img
    scale = max_side / float(longest)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return img.resize((new_w, new_h), Image.LANCZOS)

def preprocess_image_for_ocr(img: Image.Image) -> Image.Image:
    rgb = np.array(img.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    processed = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )
    kernel = np.ones((1, 1), np.uint8)
    processed = cv2.morphologyEx(processed, cv2.MORPH_OPEN, kernel)
    return Image.fromarray(processed).convert("RGB")

def extract_doctr_text_and_confidence(result) -> Tuple[str, float, List[Dict[str, Any]]]:
    all_lines = []
    confidences = []
    raw_records = []

    for page_idx, page in enumerate(result.pages, start=1):
        all_lines.append(f"--- Page {page_idx} ---")
        for block in page.blocks:
            for line in block.lines:
                words = []
                for word in line.words:
                    value = safe_str(word.value)
                    conf = float(word.confidence) if word.confidence is not None else 0.0
                    if value:
                        words.append(value)
                        confidences.append(conf)
                        raw_records.append({
                            "page": page_idx,
                            "text": value,
                            "confidence": round(conf, 4),
                            "bbox": str(word.geometry),
                        })
                line_text = " ".join(words).strip()
                if line_text:
                    all_lines.append(line_text)

    full_text = clean_text("\n".join(all_lines))
    avg_confidence = round(sum(confidences) / len(confidences), 4) if confidences else 0.0
    return full_text, avg_confidence, raw_records

def run_doctr_on_images(predictor, images: List[Image.Image]) -> Tuple[str, float, List[Dict[str, Any]]]:
    doctr_inputs = [pil_to_cv_bgr(img) for img in images]
    if torch is not None:
        with torch.inference_mode():
            result = predictor(doctr_inputs)
    else:
        result = predictor(doctr_inputs)
    return extract_doctr_text_and_confidence(result)

def build_extraction_prompt(ocr_text: str) -> str:
    return f"""
You are an expert document information extraction engine.
Your task is to accurately extract employment details from the provided OCR text of an employment-related document.

Extract exactly these keys in strict JSON format:
{{
  "Name": "",
  "Employee ID": "",
  "Company Name": "",
  "DOJ": "",
  "DOL": "",
  "Designation": "",
  "CTC": "",
  "Reason for Leaving": "",
  "Document Type": "",
  "Confidence": 0.0
}}

Rules:
1. Use ONLY the OCR text. Do not invent or guess values.
2. If a field is truly missing, return an empty string "".
3. Name must be the employee's name. Ignore HR names, manager names, signatories, and witness names.
4. Employee ID means employee code / employee no / associate id / emp id / staff id if explicitly present.
5. Company Name must be the employer or organization issuing or referenced in the document.
6. DOJ means Date of Joining.
7. DOL means Date of Leaving / Last Working Day / Relieving Date / End Date.
8. Designation means employee job title, role, or position.
9. CTC means salary / annual compensation / gross annual salary / fixed CTC if stated.
10. Reason for Leaving should be extracted only if explicitly mentioned.
11. Document Type should be one of:
   - Offer Letter
   - Appointment Letter
   - Experience Letter
   - Relieving Letter
   - Employment Verification
   - Salary Slip / Compensation
   - Resignation / Exit
   - Service Certificate
   - Employment Document
12. Keep date values exactly as seen in the document.
13. Confidence must be a number between 0.0 and 1.0.

OCR TEXT:
\"\"\"
{ocr_text}
\"\"\"
""".strip()

def ollama_extract_fields(
    ocr_text: str,
    ollama_url: str,
    model_name: str,
    timeout: int = 180,
    n_predict: int = 256,
) -> Dict[str, Any]:
    prompt = build_extraction_prompt(ocr_text[:7000])

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.0,
            "num_predict": n_predict
        }
    }

    response = requests.post(ollama_url.rstrip("/") + "/api/generate", json=payload, timeout=timeout)
    response.raise_for_status()

    result_json = response.json()
    raw_response = result_json.get("response", "{}")
    parsed = json.loads(raw_response)

    out = {
        "Name": safe_str(parsed.get("Name", "")),
        "Employee ID": safe_str(parsed.get("Employee ID", "")),
        "Company Name": safe_str(parsed.get("Company Name", "")),
        "DOJ": safe_str(parsed.get("DOJ", "")),
        "DOL": safe_str(parsed.get("DOL", "")),
        "Designation": safe_str(parsed.get("Designation", "")),
        "CTC": safe_str(parsed.get("CTC", "")),
        "Reason for Leaving": safe_str(parsed.get("Reason for Leaving", "")),
        "Document Type": safe_str(parsed.get("Document Type", "")),
        "Confidence": parsed.get("Confidence", 0.0),
    }
    return out

def detect_employment_document_type(ocr_text: str) -> str:
    text = ocr_text.lower()
    doc_type_keywords = {
        "Offer Letter": ["offer letter", "offer of employment", "employment offer", "we are pleased to offer"],
        "Appointment Letter": ["appointment letter", "appointed as", "your appointment", "terms of appointment"],
        "Experience Letter": ["experience letter", "worked with us", "during his tenure", "during her tenure", "has worked as"],
        "Relieving Letter": ["relieving letter", "relieved from services", "last working day", "date of leaving"],
        "Employment Verification": ["employment verification", "verification of employment", "this is to certify that", "employed with"],
        "Salary Slip / Compensation": ["salary slip", "pay slip", "gross salary", "net salary", "ctc"],
        "Resignation / Exit": ["resignation", "reason for leaving", "exit formalities", "separation reason"],
        "Service Certificate": ["service certificate", "certificate of employment"],
    }

    best_type = "Employment Document"
    best_score = 0
    for doc_type, keywords in doc_type_keywords.items():
        score = sum(1 for k in keywords if k in text)
        if score > best_score:
            best_score = score
            best_type = doc_type
    return best_type

def is_employment_document(ocr_text: str) -> bool:
    text = ocr_text.lower()
    employment_keywords = [
        "employee", "employer", "employment", "offer letter", "appointment letter",
        "experience letter", "relieving letter", "service certificate",
        "date of joining", "date of leaving", "designation", "salary slip",
        "pay slip", "ctc", "gross salary", "net salary", "company name",
        "employee id", "emp id", "associate id", "worked with us", "last working day"
    ]
    matches = sum(1 for kw in employment_keywords if kw in text)
    return matches >= 2

def normalize_line(line: str) -> str:
    line = clean_text(line)
    line = re.sub(r"[|]+", " ", line)
    return line.strip()

def get_clean_lines(ocr_text: str) -> List[str]:
    lines = [normalize_line(line) for line in ocr_text.splitlines()]
    return [line for line in lines if line and not line.startswith("--- Page")]

def cleanup_extracted_value(value: str) -> str:
    value = safe_str(value)
    value = re.sub(r"\s{2,}", " ", value)
    value = value.strip(" :-;,._")
    return value

def first_regex_match(lines: List[str], patterns: List[str], exclude_keywords: List[str] = None) -> str:
    exclude_keywords = exclude_keywords or []
    for line in lines:
        if any(ex.lower() in line.lower() for ex in exclude_keywords):
            continue
        for pattern in patterns:
            m = re.search(pattern, line, flags=re.IGNORECASE)
            if m:
                value = cleanup_extracted_value(m.group(1))
                if value:
                    return value
    return ""

def detect_name(lines: List[str]) -> str:
    patterns = [
        r"employee\s*name\s*[:\-]?\s*(.+)",
        r"name\s*of\s*employee\s*[:\-]?\s*(.+)",
        r"associate\s*name\s*[:\-]?\s*(.+)",
        r"staff\s*name\s*[:\-]?\s*(.+)",
        r"candidate\s*name\s*[:\-]?\s*(.+)",
        r"employee\s*[:\-]?\s*(.+)",
        r"^name\s*[:\-]?\s*(.+)",
    ]
    return first_regex_match(lines, patterns, ["company", "employer", "manager", "hr", "designation", "department"])

def detect_employee_id(lines: List[str]) -> str:
    patterns = [
        r"employee\s*id\s*[:\-]?\s*([A-Z0-9\/\-_]+)",
        r"emp\s*id\s*[:\-]?\s*([A-Z0-9\/\-_]+)",
        r"employee\s*code\s*[:\-]?\s*([A-Z0-9\/\-_]+)",
        r"associate\s*id\s*[:\-]?\s*([A-Z0-9\/\-_]+)",
        r"staff\s*id\s*[:\-]?\s*([A-Z0-9\/\-_]+)",
    ]
    return cleanup_extracted_value(first_regex_match(lines, patterns))

def detect_company_name(lines: List[str]) -> str:
    patterns = [
        r"company\s*name\s*[:\-]?\s*(.+)",
        r"employer\s*name\s*[:\-]?\s*(.+)",
        r"organization\s*name\s*[:\-]?\s*(.+)",
        r"issued\s*by\s*[:\-]?\s*(.+)",
    ]
    return cleanup_extracted_value(first_regex_match(lines, patterns))

def detect_designation(lines: List[str]) -> str:
    patterns = [
        r"designation\s*[:\-]?\s*(.+)",
        r"position\s*[:\-]?\s*(.+)",
        r"role\s*[:\-]?\s*(.+)",
        r"job\s*title\s*[:\-]?\s*(.+)",
        r"appointed\s*as\s*[:\-]?\s*(.+)",
        r"worked\s*as\s*[:\-]?\s*(.+)",
    ]
    return cleanup_extracted_value(first_regex_match(lines, patterns))

def detect_doj(lines: List[str]) -> str:
    patterns = [
        r"date\s*of\s*joining\s*[:\-]?\s*([A-Z0-9,./\- ]+)",
        r"joining\s*date\s*[:\-]?\s*([A-Z0-9,./\- ]+)",
        r"\bdoj\b\s*[:\-]?\s*([A-Z0-9,./\- ]+)",
        r"joined\s*on\s*[:\-]?\s*([A-Z0-9,./\- ]+)",
    ]
    return cleanup_extracted_value(first_regex_match(lines, patterns))

def detect_dol(lines: List[str]) -> str:
    patterns = [
        r"date\s*of\s*leaving\s*[:\-]?\s*([A-Z0-9,./\- ]+)",
        r"leaving\s*date\s*[:\-]?\s*([A-Z0-9,./\- ]+)",
        r"\bdol\b\s*[:\-]?\s*([A-Z0-9,./\- ]+)",
        r"last\s*working\s*day\s*[:\-]?\s*([A-Z0-9,./\- ]+)",
        r"relieving\s*date\s*[:\-]?\s*([A-Z0-9,./\- ]+)",
    ]
    return cleanup_extracted_value(first_regex_match(lines, patterns))

def detect_ctc(lines: List[str]) -> str:
    patterns = [
        r"\bctc\b\s*[:\-]?\s*(.+)",
        r"annual\s*ctc\s*[:\-]?\s*(.+)",
        r"cost\s*to\s*company\s*[:\-]?\s*(.+)",
        r"gross\s*annual\s*salary\s*[:\-]?\s*(.+)",
        r"annual\s*compensation\s*[:\-]?\s*(.+)",
        r"salary\s*[:\-]?\s*(.+)",
    ]
    return cleanup_extracted_value(first_regex_match(lines, patterns))

def detect_reason_for_leaving(lines: List[str]) -> str:
    patterns = [
        r"reason\s*for\s*leaving\s*[:\-]?\s*(.+)",
        r"reason\s*of\s*leaving\s*[:\-]?\s*(.+)",
        r"separation\s*reason\s*[:\-]?\s*(.+)",
        r"reason\s*for\s*exit\s*[:\-]?\s*(.+)",
        r"exit\s*reason\s*[:\-]?\s*(.+)",
    ]
    return cleanup_extracted_value(first_regex_match(lines, patterns))

def smart_extract_fields(ocr_text: str) -> Dict[str, Any]:
    lines = get_clean_lines(ocr_text)
    fields = {
        "Name": detect_name(lines),
        "Employee ID": detect_employee_id(lines),
        "Company Name": detect_company_name(lines),
        "DOJ": detect_doj(lines),
        "DOL": detect_dol(lines),
        "Designation": detect_designation(lines),
        "CTC": detect_ctc(lines),
        "Reason for Leaving": detect_reason_for_leaving(lines),
        "Document Type": detect_employment_document_type(ocr_text),
    }
    filled_count = sum(1 for v in fields.values() if safe_str(v))
    fields["Confidence"] = round(filled_count / len(fields), 2)
    return fields

def combine_confidence(ocr_conf: float, extract_conf: float) -> float:
    try:
        extract_conf = float(extract_conf)
    except Exception:
        extract_conf = 0.0
    final_conf = (0.7 * ocr_conf) + (0.3 * extract_conf)
    return round(max(0.0, min(1.0, final_conf)), 4)

def needs_review(row: Dict[str, Any]) -> bool:
    required = ["Name", "Company Name"]
    if any(not safe_str(row.get(k)) for k in required):
        return True
    if float(row.get("Confidence", 0.0)) < 0.60:
        return True
    if "Skipped" in safe_str(row.get("Status")):
        return True
    if "error" in safe_str(row.get("Extraction Mode")).lower():
        return True
    return False

def process_file(
    predictor,
    file_path: str,
    ollama_url: str,
    ollama_model: str,
    preprocess: bool = False,
    max_side: int = 1600,
    keep_raw_ocr: bool = False,
    enable_llm: bool = False,
) -> Dict[str, Any]:
    file_name = os.path.basename(file_path)

    try:
        stage_times = {}

        t0 = time.time()
        images = load_images_from_file(file_path)
        stage_times["load_sec"] = round(time.time() - t0, 2)

        t1 = time.time()
        images = [downscale_image(img, max_side=max_side) for img in images]
        stage_times["resize_sec"] = round(time.time() - t1, 2)

        if preprocess:
            t2 = time.time()
            images = [preprocess_image_for_ocr(img) for img in images]
            stage_times["preprocess_sec"] = round(time.time() - t2, 2)
        else:
            stage_times["preprocess_sec"] = 0.0

        t3 = time.time()
        ocr_text, ocr_confidence, raw_ocr = run_doctr_on_images(predictor, images)
        stage_times["ocr_sec"] = round(time.time() - t3, 2)

        row = {
            "File Name": file_name,
            "Name": "",
            "Employee ID": "",
            "Company Name": "",
            "DOJ": "",
            "DOL": "",
            "Designation": "",
            "CTC": "",
            "Reason for Leaving": "",
            "Document Type": "",
            "Confidence": 0.0,
            "OCR Confidence": round(ocr_confidence, 4),
            "OCR Text": ocr_text if keep_raw_ocr else "",
            "Status": "Skipped: not an employment document",
            "Extraction Mode": "skipped",
            "Review Required": True,
            "Load Sec": stage_times["load_sec"],
            "Resize Sec": stage_times["resize_sec"],
            "Preprocess Sec": stage_times["preprocess_sec"],
            "OCR Sec": stage_times["ocr_sec"],
            "LLM Sec": 0.0,
            "Raw OCR": json.dumps(raw_ocr, ensure_ascii=False) if keep_raw_ocr else "",
        }

        if not ocr_text:
            row["Status"] = "No text extracted"
            row["Extraction Mode"] = "none"
            return row

        ocr_text = ocr_text[:12000]

        if not is_employment_document(ocr_text):
            return row

        extracted = smart_extract_fields(ocr_text)
        extraction_mode = "smart_rules"
        llm_time = 0.0
        status = "Success"

        if enable_llm and len(ocr_text) >= 80:
            try:
                t4 = time.time()
                llm_data = ollama_extract_fields(ocr_text=ocr_text, ollama_url=ollama_url, model_name=ollama_model)
                llm_time = round(time.time() - t4, 2)

                if not safe_str(llm_data.get("Document Type")):
                    llm_data["Document Type"] = detect_employment_document_type(ocr_text)

                extracted = llm_data
                extraction_mode = "ollama"
            except Exception as llm_error:
                status = f"Processed with smart rules (Ollama issue: {str(llm_error)})"
                extraction_mode = "ollama_error"

        if not safe_str(extracted.get("Document Type")):
            extracted["Document Type"] = detect_employment_document_type(ocr_text)

        for k in [
            "Name", "Employee ID", "Company Name", "DOJ", "DOL",
            "Designation", "CTC", "Reason for Leaving", "Document Type"
        ]:
            row[k] = safe_str(extracted.get(k, ""))

        row["Confidence"] = combine_confidence(ocr_confidence, extracted.get("Confidence", 0.0))
        row["Status"] = status
        row["Extraction Mode"] = extraction_mode
        row["LLM Sec"] = llm_time
        row["Review Required"] = needs_review(row)

        return row

    except Exception as e:
        return {
            "File Name": file_name,
            "Name": "",
            "Employee ID": "",
            "Company Name": "",
            "DOJ": "",
            "DOL": "",
            "Designation": "",
            "CTC": "",
            "Reason for Leaving": "",
            "Document Type": "",
            "Confidence": 0.0,
            "OCR Confidence": 0.0,
            "OCR Text": "",
            "Status": f"Error: {str(e)}",
            "Extraction Mode": "error",
            "Review Required": True,
            "Load Sec": 0.0,
            "Resize Sec": 0.0,
            "Preprocess Sec": 0.0,
            "OCR Sec": 0.0,
            "LLM Sec": 0.0,
            "Raw OCR": "",
        }

def csv_fieldnames() -> List[str]:
    return [
        "File Name", "Name", "Employee ID", "Company Name", "DOJ", "DOL",
        "Designation", "CTC", "Reason for Leaving", "Document Type",
        "Confidence", "OCR Confidence", "Status", "Extraction Mode",
        "Review Required", "Load Sec", "Resize Sec", "Preprocess Sec",
        "OCR Sec", "LLM Sec",
    ]

def init_csv(output_file: str) -> None:
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fieldnames())
        writer.writeheader()

def append_csv_row(output_file: str, row: Dict[str, Any]) -> None:
    with open(output_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fieldnames())
        writer.writerow({k: row.get(k, "") for k in csv_fieldnames()})

def save_json(records: List[Dict[str, Any]], output_file: str) -> None:
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

def run(inputpath, outputpath, kwargs, log_queue=None):
    log_queue = log_queue or []
    ensure_dir(outputpath)

    files = kwargs.get("employment_files", [])
    preprocess = kwargs.get("preprocess", "No") == "Yes"
    max_side = int(kwargs.get("max_side", "1600"))
    keep_raw_ocr = kwargs.get("keep_raw_ocr", "No") == "Yes"
    enable_llm = kwargs.get("enable_llm", "Yes") == "Yes"
    ollama_url = kwargs.get("ollama_url", "http://localhost:11434").strip()
    ollama_model = kwargs.get("ollama_model", "llama3.1").strip()

    if not files:
        raise ValueError("Please provide at least one employment document.")
    if ocr_predictor is None:
        raise ImportError("docTR is not installed. Install it with: pip install python-doctr")

    if torch is not None:
        try:
            torch.set_num_threads(4)
            torch.set_grad_enabled(False)
        except Exception:
            pass

    valid_files = [f for f in files if os.path.isfile(f) and is_supported_file(f)]
    if not valid_files:
        raise ValueError("No supported files found.")

    push_log(log_queue, "INFO", "Loading docTR model")
    predictor = ocr_predictor(det_arch="fast_base", reco_arch="crnn_vgg16_bn", pretrained=True)

    csv_output = os.path.join(outputpath, "employment_output.csv")
    json_output = os.path.join(outputpath, "employment_output.json")
    review_output = os.path.join(outputpath, "employment_review.csv")
    excel_output = os.path.join(outputpath, "employment_output.xlsx")

    init_csv(csv_output)
    init_csv(review_output)

    results = []

    for idx, file_path in enumerate(valid_files, start=1):
        push_log(log_queue, "INFO", f"[{idx}/{len(valid_files)}] Processing {os.path.basename(file_path)}")
        result = process_file(
            predictor=predictor,
            file_path=file_path,
            ollama_url=ollama_url,
            ollama_model=ollama_model,
            preprocess=preprocess,
            max_side=max_side,
            keep_raw_ocr=keep_raw_ocr,
            enable_llm=enable_llm,
        )
        results.append(result)
        append_csv_row(csv_output, result)

        if result.get("Review Required", False):
            append_csv_row(review_output, result)

    save_json(results, json_output)
    pd.DataFrame(results).to_excel(excel_output, index=False)

    review_count = sum(1 for r in results if r.get("Review Required"))
    summary_path = os.path.join(outputpath, "employment_summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"Processed files: {len(results)}\n")
        f.write(f"Review count: {review_count}\n")
        f.write(f"Ollama enabled: {enable_llm}\n")
        f.write(f"Model: {ollama_model}\n")

    push_log(log_queue, "SUCCESS", f"Employment OCR completed for {len(results)} files. Review count: {review_count}")
    return {
        "output_files": [summary_path, csv_output, review_output, json_output, excel_output]
    }