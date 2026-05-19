from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Dict
import pandas as pd

from core.logging_utils import push_log

DESCRIPTION = "Clean a selected name column and create simple category flags such as blank, initials-only, or normal."
BADGES = ["Name cleanup", "Category flags", "Ready to export"]
ASSISTANT_HINT = "Upload one file, choose the name column, and export the cleaned output with helper flags."

PARAMS = [
    {"name": "input_file", "type": "file", "label": "Upload CSV / Excel file"},
    {"name": "name_column", "type": "column", "label": "Name column", "source": "input_file"},
    {"name": "output_type", "type": "select", "label": "Output file type", "options": ["xlsx", "csv"], "default": "xlsx"},
]


def _read_file(fp: str) -> pd.DataFrame:
    if fp.lower().endswith(".csv"):
        return pd.read_csv(fp)
    return pd.read_excel(fp)


def _clean_name(value: Any) -> str:
    text = re.sub(r"[^A-Za-z\s]", " ", str(value or ""))
    return " ".join(text.split()).strip().title()


def _category(value: str) -> str:
    if not value:
        return "blank"
    parts = value.split()
    if all(len(p) == 1 for p in parts):
        return "initials_only"
    if len(parts) == 1:
        return "single_token"
    return "normal"


def run(inputpath: str, outputpath: str, kwargs: Dict[str, Any], log_queue=None) -> Dict[str, Any]:
    log_queue = log_queue or []
    fp = kwargs.get("input_file")
    col = kwargs.get("name_column")
    
    if not fp or not col:
        raise ValueError("Please upload a file and select the name column.")
        
    df = _read_file(fp)
    
    push_log(log_queue, "INFO", "Processing names...")
    df[f"{col}_cleaned"] = df[col].apply(_clean_name)
    df[f"{col}_category"] = df[f"{col}_cleaned"].apply(_category)
    
    ext = kwargs.get("output_type", "xlsx")
    out_path = os.path.join(outputpath, f"name_cleaned_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}")
    
    if ext == "xlsx":
        df.to_excel(out_path, index=False)
    else:
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        
    push_log(log_queue, "SUCCESS", "Name cleaning completed")
    
    return {
        "output_files": [out_path],
    }