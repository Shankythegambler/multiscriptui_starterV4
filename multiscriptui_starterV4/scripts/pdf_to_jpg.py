import os
from pathlib import Path

import pandas as pd
from pdf2image import convert_from_path

from core.io_utils import ensure_dir, zip_paths
from core.logging_utils import push_log


DESCRIPTION = "Convert one or more PDFs into JPG images, one image per page."
BADGES = ["Page-wise JPG", "ZIP output", "Offline"]
ASSISTANT_HINT = "Provide one or more PDFs. If Poppler is not in PATH, enter the local Poppler bin path."
SUPPORTS_LOCAL_PATHS = True

PARAMS = [
    {"name": "pdf_files", "type": "files", "label": "PDF files"},
    {"name": "dpi", "type": "select", "label": "DPI", "options": ["150", "200", "300"], "default": "300"},
    {"name": "poppler_path", "type": "text", "label": "Optional Poppler bin path"},
]


def run(inputpath, outputpath, kwargs, log_queue=None):
    log_queue = log_queue or []
    ensure_dir(outputpath)

    pdf_files = kwargs.get("pdf_files", [])
    dpi = int(kwargs.get("dpi", "300"))
    poppler_path = kwargs.get("poppler_path", "").strip()

    if not pdf_files:
        raise ValueError("Please provide at least one PDF.")

    all_images = []
    summary_rows = []

    for pdf_file in pdf_files:
        try:
            push_log(log_queue, "INFO", f"Converting {os.path.basename(pdf_file)}")
            if poppler_path:
                images = convert_from_path(pdf_file, dpi=dpi, fmt="jpeg", poppler_path=poppler_path)
            else:
                images = convert_from_path(pdf_file, dpi=dpi, fmt="jpeg")

            total_pages = len(images)
            created_files = []

            for i, image in enumerate(images, start=1):
                if total_pages == 1:
                    out_file = os.path.join(outputpath, f"{Path(pdf_file).stem}.jpg")
                else:
                    out_file = os.path.join(outputpath, f"{Path(pdf_file).stem}.pg{i}.jpg")
                image.save(out_file, "JPEG")
                all_images.append(out_file)
                created_files.append(out_file)

            summary_rows.append({
                "pdf_file": os.path.basename(pdf_file),
                "status": "Converted",
                "pages": total_pages,
                "dpi": dpi,
            })

        except Exception as e:
            summary_rows.append({
                "pdf_file": os.path.basename(pdf_file),
                "status": f"Failed: {e}",
                "pages": 0,
                "dpi": dpi,
            })
            push_log(log_queue, "ERROR", f"Failed {os.path.basename(pdf_file)}: {e}")

    summary_path = os.path.join(outputpath, "pdf_to_jpg_summary.xlsx")
    pd.DataFrame(summary_rows).to_excel(summary_path, index=False)

    output_files = [summary_path]
    if all_images:
        zip_path = os.path.join(outputpath, "pdf_to_jpg_images.zip")
        zip_paths(all_images, zip_path)
        output_files.append(zip_path)
        output_files.extend(all_images)

    push_log(log_queue, "SUCCESS", f"Converted {len(all_images)} image files")
    return {"output_files": output_files}