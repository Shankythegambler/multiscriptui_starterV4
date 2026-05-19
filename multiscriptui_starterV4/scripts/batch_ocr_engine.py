import os
import re
import time
from typing import List, Dict, Any, Tuple
from pathlib import Path
import pandas as pd
import numpy as np
import cv2
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

DESCRIPTION = "Step 1: Batch OCR Engine. Scans folders of PDFs/Images and extracts raw text into an Excel file for later LLM processing."
BADGES = ["docTR", "Batch Processing", "Folder Scan"]
ASSISTANT_HINT = "Point this to a folder of 1,000+ documents. It will run offline and output a raw text spreadsheet."
SUPPORTS_LOCAL_PATHS = True

PARAMS = [
    {"name": "input_paths", "type": "files", "label": "Upload files or provide local folder paths"},
    {"name": "preprocess", "type": "select", "label": "Enable OpenCV preprocessing", "options": ["No", "Yes"], "default": "No"},
    {"name": "max_side", "type": "select", "label": "Max image side length", "options": ["1200", "1600", "2000"], "default": "1600"},
]

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".pdf"}

def clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def pil_to_cv_bgr(img: Image.Image) -> np.ndarray:
    arr = np.array(img.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

def load_images_from_file(file_path: str, max_side: int) -> List[Image.Image]:
    ext = os.path.splitext(file_path.lower())[1]
    images = []
    if ext == ".pdf":
        if pdfium is None:
            raise ImportError("pypdfium2 required for PDFs.")
        pdf = pdfium.PdfDocument(file_path)
        for i in range(len(pdf)):
            bitmap = pdf[i].render(scale=1.5)
            images.append(bitmap.to_pil().convert("RGB"))
        pdf.close()
    else:
        images.append(Image.open(file_path).convert("RGB"))

    # Downscale
    resized = []
    for img in images:
        w, h = img.size
        longest = max(w, h)
        if longest > max_side:
            scale = max_side / float(longest)
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        resized.append(img)
    return resized

def preprocess_image(img: Image.Image) -> Image.Image:
    rgb = np.array(img)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    processed = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)
    kernel = np.ones((1, 1), np.uint8)
    processed = cv2.morphologyEx(processed, cv2.MORPH_OPEN, kernel)
    return Image.fromarray(processed).convert("RGB")

def run(inputpath, outputpath, kwargs, log_queue=None):
    log_queue = log_queue or []
    ensure_dir(outputpath)

    raw_files = kwargs.get("input_paths", [])
    preprocess = kwargs.get("preprocess", "No") == "Yes"
    max_side = int(kwargs.get("max_side", "1600"))

    # Folder expansion
    files = []
    for path in raw_files:
        if os.path.isdir(path):
            push_log(log_queue, "INFO", f"Scanning directory: {path}")
            for root, _, filenames in os.walk(path):
                for fname in filenames:
                    if os.path.splitext(fname)[1].lower() in SUPPORTED_EXTENSIONS:
                        files.append(os.path.join(root, fname))
        elif os.path.isfile(path) and os.path.splitext(path)[1].lower() in SUPPORTED_EXTENSIONS:
            files.append(path)

    if not files:
        raise ValueError("No supported files found to process.")

    push_log(log_queue, "INFO", "Loading docTR OCR model...")
    predictor = ocr_predictor(det_arch="fast_base", reco_arch="crnn_vgg16_bn", pretrained=True)

    results = []
    total = len(files)

    for idx, fp in enumerate(files, start=1):
        file_name = os.path.basename(fp)
        push_log(log_queue, "INFO", f"[{idx}/{total}] OCR processing: {file_name}")
        try:
            images = load_images_from_file(fp, max_side)
            if preprocess:
                images = [preprocess_image(img) for img in images]

            doctr_inputs = [pil_to_cv_bgr(img) for img in images]
            ocr_result = predictor(doctr_inputs)

            text_lines = []
            for page in ocr_result.pages:
                for block in page.blocks:
                    for line in block.lines:
                        words = [w.value for w in line.words if w.value]
                        text_lines.append(" ".join(words))

            full_text = clean_text("\n".join(text_lines))
            
            results.append({
                "File_Name": file_name,
                "Original_Path": fp,
                "Page_Count": len(images),
                "Raw_OCR_Text": full_text
            })
        except Exception as e:
            push_log(log_queue, "ERROR", f"[{idx}/{total}] Failed OCR for {file_name}: {e}")
            results.append({
                "File_Name": file_name,
                "Original_Path": fp,
                "Page_Count": 0,
                "Raw_OCR_Text": f"ERROR: {e}"
            })

    df = pd.DataFrame(results)
    out_path = os.path.join(outputpath, "Batch_OCR_Results.xlsx")
    df.to_excel(out_path, index=False)
    push_log(log_queue, "SUCCESS", f"OCR complete! Data saved to {out_path}")

    return {"output_files": [out_path]}