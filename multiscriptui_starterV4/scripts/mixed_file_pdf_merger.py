from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
from fpdf import FPDF
from PIL import Image
from PyPDF2 import PdfMerger, PdfReader

from core.logging_utils import push_log

KEY = "mixed_file_pdf_merger"
TITLE = "Mixed File PDF Merger"
ICON = "🧾"
CATEGORY = "Document Operations"
BADGES = ["PDF + Image + Excel", "Skipped log", "Single merged PDF"]
DESCRIPTION = "Merge uploaded PDFs, images, and Excel files into one PDF. Images and Excel sheets are converted to temporary PDFs before merge."
ASSISTANT_HINT = "Upload any mix of PDF, JPG, PNG, WEBP, XLS, or XLSX files. The tool converts supported files and returns one merged PDF plus a skipped-file log if needed."

PARAMS = [
    {"name": "source_files", "type": "multi_file", "label": "Upload PDFs, images, and Excel files"},
]

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
EXCEL_EXTS = {".xls", ".xlsx"}
PDF_EXTS = {".pdf"}


def _natural_sort_key(path: str) -> str:
    return str(path).lower()


def _safe_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).encode("latin-1", "replace").decode("latin-1")


def _is_pdf_usable(pdf_path: str) -> Tuple[bool, str]:
    try:
        reader = PdfReader(pdf_path)
        if reader.is_encrypted:
            decrypt_result = reader.decrypt("")
            if decrypt_result == 0:
                return False, "Password protected"
        _ = len(reader.pages)
        return True, ""
    except Exception as e:
        return False, str(e)


def _convert_image_to_pdf(image_path: str, temp_dir: str) -> Tuple[str | None, str]:
    try:
        image = Image.open(image_path)
        if image.mode != "RGB":
            image = image.convert("RGB")
        pdf_path = os.path.join(temp_dir, f"{Path(image_path).stem}_image_converted.pdf")
        image.save(pdf_path, "PDF", resolution=100.0)
        return pdf_path, ""
    except Exception as e:
        return None, str(e)


def _convert_excel_to_pdf(excel_path: str, temp_dir: str) -> Tuple[str | None, str]:
    try:
        xls = pd.ExcelFile(excel_path)
        pdf = FPDF(orientation="L", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=10)
        for sheet_name in xls.sheet_names:
            try:
                df = pd.read_excel(excel_path, sheet_name=sheet_name, dtype=str).fillna("")
                pdf.add_page()
                pdf.set_font("Helvetica", "B", 12)
                pdf.cell(0, 10, _safe_text(f"File: {Path(excel_path).name} | Sheet: {sheet_name}"), new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", size=8)
                if df.empty:
                    pdf.cell(0, 8, "No data found in this sheet.", new_x="LMARGIN", new_y="NEXT")
                    continue
                max_cols = min(len(df.columns), 8)
                display_df = df.iloc[:, :max_cols]
                col_width = 277 / max_cols
                row_height = 6
                for col in display_df.columns:
                    pdf.cell(col_width, row_height, _safe_text(col)[:30], border=1)
                pdf.ln(row_height)
                max_rows = min(len(display_df), 200)
                for _, row in display_df.head(max_rows).iterrows():
                    for cell in row:
                        pdf.cell(col_width, row_height, _safe_text(cell)[:30], border=1)
                    pdf.ln(row_height)
                if len(display_df) > max_rows:
                    pdf.ln(2)
                    pdf.cell(0, 8, _safe_text(f"Preview truncated to first {max_rows} rows."), new_x="LMARGIN", new_y="NEXT")
            except Exception as sheet_error:
                pdf.add_page()
                pdf.set_font("Helvetica", size=10)
                pdf.cell(0, 10, _safe_text(f"Could not read sheet {sheet_name}: {sheet_error}"), new_x="LMARGIN", new_y="NEXT")
        output_pdf = os.path.join(temp_dir, f"{Path(excel_path).stem}_excel_converted.pdf")
        pdf.output(output_pdf)
        return output_pdf, ""
    except Exception as e:
        return None, str(e)


def run(inputpath: str, outputpath: str, kwargs: Dict[str, Any], log_queue=None) -> Dict[str, Any]:
    log_queue = log_queue or []
    files: List[str] = kwargs.get("source_files") or []
    if not files:
        raise ValueError("Please upload at least one file.")

    temp_dir = os.path.join(outputpath, "_temp_pdf_conversion")
    os.makedirs(temp_dir, exist_ok=True)
    candidate_pdfs: List[str] = []
    skipped: List[Tuple[str, str]] = []

    for file_path in sorted(files, key=_natural_sort_key):
        suffix = Path(file_path).suffix.lower()
        name = os.path.basename(file_path)
        if suffix in PDF_EXTS:
            usable, reason = _is_pdf_usable(file_path)
            if usable:
                candidate_pdfs.append(file_path)
                push_log(log_queue, "INFO", f"Added PDF: {name}")
            else:
                skipped.append((name, reason))
                push_log(log_queue, "WARN", f"Skipped PDF: {name} | {reason}")
        elif suffix in IMAGE_EXTS:
            converted, reason = _convert_image_to_pdf(file_path, temp_dir)
            if converted:
                candidate_pdfs.append(converted)
                push_log(log_queue, "INFO", f"Converted image: {name}")
            else:
                skipped.append((name, reason))
                push_log(log_queue, "WARN", f"Skipped image: {name} | {reason}")
        elif suffix in EXCEL_EXTS:
            converted, reason = _convert_excel_to_pdf(file_path, temp_dir)
            if converted:
                candidate_pdfs.append(converted)
                push_log(log_queue, "INFO", f"Converted Excel: {name}")
            else:
                skipped.append((name, reason))
                push_log(log_queue, "WARN", f"Skipped Excel: {name} | {reason}")
        else:
            skipped.append((name, "Unsupported format"))
            push_log(log_queue, "WARN", f"Skipped unsupported file: {name}")

    if not candidate_pdfs:
        raise ValueError("No supported and readable files were available to merge.")

    merger = PdfMerger()
    for pdf_path in sorted(candidate_pdfs, key=_natural_sort_key):
        merger.append(pdf_path)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    merged_path = os.path.join(outputpath, f"mixed_merged_{ts}.pdf")
    merger.write(merged_path)
    merger.close()

    output_files = [merged_path]
    if skipped:
        skipped_log = os.path.join(outputpath, f"mixed_merged_skipped_{ts}.txt")
        with open(skipped_log, "w", encoding="utf-8") as f:
            f.write("Skipped files log\n\n")
            for file_name, reason in skipped:
                f.write(f"{file_name} --> {reason}\n")
        output_files.append(skipped_log)

    push_log(log_queue, "SUCCESS", f"Merged {len(candidate_pdfs)} converted/readable file(s)")
    return {
        "message": "Mixed File PDF Merger completed.",
        "stats": {"merged_inputs": len(candidate_pdfs), "skipped_inputs": len(skipped)},
        "output_files": output_files,
    }
