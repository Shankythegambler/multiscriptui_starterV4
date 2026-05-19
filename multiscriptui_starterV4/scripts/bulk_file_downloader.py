from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict

import pandas as pd
import requests

from core.logging_utils import push_log

DESCRIPTION = "Download files from URLs listed in an uploaded sheet and generate a download report."
BADGES = ["URL based", "Report output", "Starter version"]
ASSISTANT_HINT = "Upload one sheet with a URL column. The starter version downloads direct links only."

PARAMS = [
    {"name": "input_file", "type": "file", "label": "Upload CSV / Excel file"},
    {"name": "url_column", "type": "column", "label": "URL column", "source": "input_file"},
]


def _read_file(fp: str) -> pd.DataFrame:
    if fp.lower().endswith(".csv"):
        return pd.read_csv(fp)
    return pd.read_excel(fp)


def run(inputpath: str, outputpath: str, kwargs: Dict[str, Any], log_queue=None) -> Dict[str, Any]:
    log_queue = log_queue or []
    fp = kwargs.get("input_file")
    col = kwargs.get("url_column")
    
    if not fp or not col:
        raise ValueError("Please upload a file and select the URL column.")
        
    df = _read_file(fp).fillna("")
    dl_dir = os.path.join(outputpath, "downloads")
    os.makedirs(dl_dir, exist_ok=True)
    
    rows = []
    done = 0
    
    for idx, url in enumerate(df[col].astype(str), start=1):
        url = url.strip()
        if not url:
            rows.append({"row_number": idx + 1, "status": "blank", "saved_file": ""})
            continue
            
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            fname = f"download_{idx}"
            
            # Simple extension extraction
            ext = os.path.splitext(url.split('?')[0])[1] or ".bin"
            
            path = os.path.join(dl_dir, fname + ext)
            with open(path, "wb") as f:
                f.write(r.content)
                
            rows.append({"row_number": idx + 1, "status": "success", "saved_file": os.path.basename(path)})
            done += 1
            push_log(log_queue, "INFO", f"Downloaded file {idx}")
        except Exception as e:
            rows.append({"row_number": idx + 1, "status": f"failed: {e}", "saved_file": ""})
            push_log(log_queue, "ERROR", f"Failed to download row {idx+1}: {e}")
            
    report = pd.DataFrame(rows)
    report_path = os.path.join(outputpath, f"download_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
    report.to_excel(report_path, index=False)
    
    push_log(log_queue, "SUCCESS", f"Downloaded {done} file(s)")
    return {
        "output_files": [report_path]
    }