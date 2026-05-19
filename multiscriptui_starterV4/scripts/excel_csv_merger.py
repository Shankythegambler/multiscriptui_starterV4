from __future__ import annotations

import os
from typing import Any, Dict, List

import pandas as pd

from core.io_utils import read_table
from core.logging_utils import push_log

KEY = "excel_csv_merger"
ICON = "📊"
TITLE = "Excel / CSV Merger"
CATEGORY = "Data Preparation"
BADGES = ["Fast setup", "Multi-file", "Source tracking"]
DESCRIPTION = (
    "Combine multiple CSV or Excel files into one clean output. Each record is tagged with its source file "
    "so you can trace where it came from. Best for monthly dumps, client data packs, and operational rollups."
)
ASSISTANT_HINT = (
    "Upload at least two files with similar structure. The tool will stack them row-wise and add a source_file column."
)
PARAMS = [
    {"name": "input_files", "type": "multi_file", "label": "Upload CSV / Excel files"},
    {
        "name": "output_name",
        "type": "text",
        "label": "Output file name",
        "default": "merged_output.xlsx",
    },
    {
        "name": "output_format",
        "type": "select",
        "label": "Output format",
        "options": ["xlsx", "csv"],
        "default": "xlsx",
    },
]


def run(inputpath: str, outputpath: str, kwargs: Dict[str, Any], log_queue=None, progress_state=None) -> Dict[str, Any]:
    log_queue = log_queue or []
    files: List[str] = kwargs["input_files"]
    output_name = kwargs.get("output_name", "merged_output.xlsx").strip() or "merged_output.xlsx"
    output_format = kwargs.get("output_format", "xlsx")

    if len(files) < 2:
        raise ValueError("Please upload at least two files.")

    frames = []
    for file_path in files:
        push_log(log_queue, "INFO", f"Loading {os.path.basename(file_path)}")
        df = read_table(file_path)
        df["source_file"] = os.path.basename(file_path)
        frames.append(df)

    merged = pd.concat(frames, ignore_index=True)
    push_log(log_queue, "SUCCESS", f"Merged {len(files)} files into {len(merged):,} rows")

    base_name, _ = os.path.splitext(output_name)
    final_name = f"{base_name}.{output_format}"
    final_path = os.path.join(outputpath, final_name)

    if output_format == "csv":
        merged.to_csv(final_path, index=False, encoding="utf-8-sig")
    else:
        merged.to_excel(final_path, index=False)

    return {
        "success": True,
        "message": "Merge completed successfully.",
        "output_files": [final_path],
        "stats": {
            "input_files": len(files),
            "rows": int(len(merged)),
            "columns": int(len(merged.columns)),
        },
    }
