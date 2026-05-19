from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Any, Dict, List

from core.logging_utils import push_log

KEY = "file_zipper"
ICON = "🗜️"
TITLE = "File Zipper"
CATEGORY = "Utilities"
BADGES = ["Batch packaging", "Size cap", "Simple delivery"]
DESCRIPTION = (
    "Bundle multiple uploaded files into zip packages. You can keep everything in one archive or split into parts "
    "based on a maximum size threshold."
)
ASSISTANT_HINT = (
    "Use this when you need to package reports, PDFs, or exports before sharing them with a client or another team."
)
PARAMS = [
    {"name": "input_files", "type": "multi_file", "label": "Upload files to zip"},
    {
        "name": "zip_base_name",
        "type": "text",
        "label": "Zip base name",
        "default": "archive",
    },
    {
        "name": "max_size_mb",
        "type": "number",
        "label": "Max size per zip (MB)",
        "default": 20,
        "min": 1,
        "step": 1,
    },
]


def _chunk_by_size(files: List[str], max_size_mb: float) -> List[List[str]]:
    chunks: List[List[str]] = []
    current: List[str] = []
    current_size = 0.0

    for file_path in files:
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if size_mb > max_size_mb:
            continue
        if current and current_size + size_mb > max_size_mb:
            chunks.append(current)
            current = []
            current_size = 0.0
        current.append(file_path)
        current_size += size_mb

    if current:
        chunks.append(current)
    return chunks



def run(inputpath: str, outputpath: str, kwargs: Dict[str, Any], log_queue=None, progress_state=None) -> Dict[str, Any]:
    log_queue = log_queue or []
    files: List[str] = kwargs["input_files"]
    zip_base_name = kwargs.get("zip_base_name", "archive").strip() or "archive"
    max_size_mb = float(kwargs.get("max_size_mb", 20))

    if not files:
        raise ValueError("Please upload at least one file.")

    output_files: List[str] = []
    chunks = _chunk_by_size(files, max_size_mb)
    if not chunks:
        raise ValueError("No files could be zipped under the selected size limit.")

    for idx, chunk in enumerate(chunks, start=1):
        zip_name = f"{zip_base_name}_part_{idx}.zip" if len(chunks) > 1 else f"{zip_base_name}.zip"
        zip_path = os.path.join(outputpath, zip_name)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in chunk:
                zf.write(file_path, arcname=Path(file_path).name)
        output_files.append(zip_path)
        push_log(log_queue, "SUCCESS", f"Created {zip_name}")

    return {
        "success": True,
        "message": "Zip packaging completed successfully.",
        "output_files": output_files,
        "stats": {
            "input_files": len(files),
            "zip_parts": len(output_files),
        },
    }
