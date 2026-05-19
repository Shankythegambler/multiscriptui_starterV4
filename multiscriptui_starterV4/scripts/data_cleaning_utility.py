from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict
import pandas as pd

from core.logging_utils import push_log

DESCRIPTION = "Clean a tabular file by trimming spaces, normalising blanks, and optionally removing duplicate rows."
BADGES = ["Trim", "Deduplicate", "Null cleanup"]
ASSISTANT_HINT = "Upload one file, choose whether to remove duplicates, and export the cleaned result."

PARAMS = [
    {"name": "input_file", "type": "file", "label": "Upload CSV / Excel file"},
    {"name": "remove_duplicates", "type": "select", "label": "Remove duplicate rows", "options": ["no", "yes"], "default": "yes"},
    {"name": "output_type", "type": "select", "label": "Output file type", "options": ["xlsx", "csv"], "default": "xlsx"},
]


def _read_file(fp: str) -> pd.DataFrame:
    if fp.lower().endswith(".csv"):
        return pd.read_csv(fp)
    return pd.read_excel(fp)


def run(inputpath: str, outputpath: str, kwargs: Dict[str, Any], log_queue=None) -> Dict[str, Any]:
    log_queue = log_queue or []
    fp = kwargs.get("input_file")
    if not fp:
        raise ValueError("Please upload an input file.")

    df = _read_file(fp)
    before = len(df)
    push_log(log_queue, "INFO", f"Loaded {before} row(s)")
    
    df = df.fillna("")
    
    # Modern approach to clean all string columns (replaces deprecated applymap)
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].astype(str).replace(r'\s+', ' ', regex=True).str.strip()

    if kwargs.get("remove_duplicates", "yes") == "yes":
        df = df.drop_duplicates()
        
    after = len(df)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = kwargs.get("output_type", "xlsx")
    out_path = os.path.join(outputpath, f"data_cleaned_{stamp}.{ext}")
    
    if ext == "xlsx":
        df.to_excel(out_path, index=False)
    else:
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        
    push_log(log_queue, "SUCCESS", f"Cleaned file saved with {after} row(s)")
    
    return {
        "output_files": [out_path],
    }