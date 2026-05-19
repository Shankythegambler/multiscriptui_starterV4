import os
from pathlib import Path

import pdfplumber
import pandas as pd

from core.io_utils import ensure_dir
from core.logging_utils import push_log


DESCRIPTION = "Convert PDFs to a single-sheet Excel output. Tries table extraction first, then text fallback."
BADGES = ["Single sheet", "Text fallback", "Offline"]
ASSISTANT_HINT = "Upload one or more PDFs. Output will contain one combined sheet across all files."
SUPPORTS_LOCAL_PATHS = False

PARAMS = [
    {"name": "pdf_files", "type": "files", "label": "Upload PDF files"},
]


def _extract_from_pdf(pdf_path: str, log_queue):
    combined_rows = []
    pages_with_tables = 0
    pages_with_text = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            table = None
            try:
                table = page.extract_table()
            except Exception:
                table = None

            if table and len(table) > 1:
                headers = table[0]
                for row in table[1:]:
                    row_dict = {str(headers[i]): (row[i] if i < len(row) else "") for i in range(len(headers))}
                    row_dict["_source_pdf"] = os.path.basename(pdf_path)
                    row_dict["_page_no"] = page_no
                    row_dict["_extract_mode"] = "table"
                    combined_rows.append(row_dict)
                pages_with_tables += 1
            else:
                try:
                    text = page.extract_text() or ""
                except Exception:
                    text = ""

                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                if lines:
                    for line_idx, line in enumerate(lines, start=1):
                        combined_rows.append({
                            "content": line,
                            "_source_pdf": os.path.basename(pdf_path),
                            "_page_no": page_no,
                            "_line_no": line_idx,
                            "_extract_mode": "text",
                        })
                    pages_with_text += 1

    return combined_rows, pages_with_tables, pages_with_text


def run(inputpath, outputpath, kwargs, log_queue=None):
    log_queue = log_queue or []
    ensure_dir(outputpath)

    pdf_files = kwargs.get("pdf_files", [])
    if not pdf_files:
        raise ValueError("Please upload at least one PDF file.")

    final_rows = []
    summary_rows = []

    for pdf_file in pdf_files:
        push_log(log_queue, "INFO", f"Processing PDF: {os.path.basename(pdf_file)}")
        try:
            rows, table_pages, text_pages = _extract_from_pdf(pdf_file, log_queue)
            final_rows.extend(rows)
            summary_rows.append({
                "pdf_file": os.path.basename(pdf_file),
                "status": "Processed",
                "rows_extracted": len(rows),
                "pages_with_tables": table_pages,
                "pages_with_text": text_pages,
            })
        except Exception as e:
            summary_rows.append({
                "pdf_file": os.path.basename(pdf_file),
                "status": f"Failed: {e}",
                "rows_extracted": 0,
                "pages_with_tables": 0,
                "pages_with_text": 0,
            })
            push_log(log_queue, "ERROR", f"Failed PDF {pdf_file}: {e}")

    combined_df = pd.DataFrame(final_rows) if final_rows else pd.DataFrame(columns=["content", "_source_pdf", "_page_no", "_extract_mode"])
    summary_df = pd.DataFrame(summary_rows)

    output_excel = os.path.join(outputpath, "pdf_to_excel_combined.xlsx")
    with pd.ExcelWriter(output_excel, engine="openpyxl") as writer:
        combined_df.to_excel(writer, index=False, sheet_name="combined_output")
        summary_df.to_excel(writer, index=False, sheet_name="summary")

    push_log(log_queue, "SUCCESS", f"Completed {len(pdf_files)} PDFs.")
    return {"output_files": [output_excel]}