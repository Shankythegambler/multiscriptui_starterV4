import os
import re
from pathlib import Path
from datetime import datetime
import pandas as pd

from core.logging_utils import push_log
from core.io_utils import ensure_dir

DESCRIPTION = "Search for multiple terms across single or multiple Excel/CSV files in a folder, pulling all matching rows into a single report."
BADGES = ["Folder Scan", "Batch Search", "Data Aggregation"]
ASSISTANT_HINT = "Point this to a folder of files. You can paste search terms manually, or upload a reference file containing a massive list of IDs/Names."
SUPPORTS_LOCAL_PATHS = True

PARAMS = [
    {"name": "input_paths", "type": "files", "label": "Data to search (Local Folders or Files)"},
    {"name": "search_terms", "type": "textarea", "label": "Search Terms (Paste here, one per line)", "help": "Leave blank if uploading a reference file below."},
    {"name": "ref_file", "type": "file", "label": "OR Upload Reference File (CSV/Excel)"},
    {"name": "ref_column", "type": "column", "label": "Reference Column", "source": "ref_file"},
    {"name": "match_type", "type": "select", "label": "Match Type", "options": ["Exact match", "Partial match"], "default": "Exact match"},
    {"name": "case_sensitive", "type": "select", "label": "Case Sensitive?", "options": ["No", "Yes"], "default": "No"},
]

def _read_table(fp: str) -> pd.DataFrame:
    if fp.lower().endswith(".csv"):
        return pd.read_csv(fp, dtype=str).fillna("")
    return pd.read_excel(fp, dtype=str).fillna("")

def run(inputpath, outputpath, kwargs, log_queue=None):
    log_queue = log_queue or []
    ensure_dir(outputpath)
    
    raw_paths = kwargs.get("input_paths", [])
    raw_terms = kwargs.get("search_terms", "")
    ref_file = kwargs.get("ref_file")
    ref_column = kwargs.get("ref_column", "").strip()
    match_type = kwargs.get("match_type", "Exact match")
    case_sensitive = kwargs.get("case_sensitive", "No") == "Yes"
    
    # --- 1. Compile Search Terms ---
    search_terms = [t.strip() for t in raw_terms.splitlines() if t.strip()]
    
    # If a reference file is provided, append those terms to our list
    if ref_file and ref_column:
        try:
            push_log(log_queue, "INFO", "Loading reference file for search terms...")
            ref_df = _read_table(ref_file)
            if ref_column in ref_df.columns:
                file_terms = ref_df[ref_column].dropna().astype(str).str.strip().tolist()
                search_terms.extend([t for t in file_terms if t])
            else:
                push_log(log_queue, "WARNING", f"Column '{ref_column}' not found in reference file.")
        except Exception as e:
            push_log(log_queue, "ERROR", f"Failed to load reference file: {e}")
            
    # Deduplicate terms
    search_terms = list(set(search_terms))
    
    if not search_terms:
        raise ValueError("Please provide at least one search term (either pasted or via a reference file).")
        
    push_log(log_queue, "INFO", f"Loaded {len(search_terms)} unique search terms.")
        
    # --- 2. Expand Folders and Find Valid Files ---
    valid_exts = {".csv", ".xlsx", ".xls"}
    files_to_search = []
    
    for path in raw_paths:
        if os.path.isdir(path):
            push_log(log_queue, "INFO", f"Scanning folder: {path}")
            for root, _, files in os.walk(path):
                for file in files:
                    if os.path.splitext(file)[1].lower() in valid_exts:
                        files_to_search.append(os.path.join(root, file))
        elif os.path.isfile(path) and os.path.splitext(path)[1].lower() in valid_exts:
            files_to_search.append(path)
            
    if not files_to_search:
        raise ValueError("No valid CSV or Excel files found in the provided paths.")
        
    # --- 3. Perform the Multi-Search ---
    all_matches = []
    total_files = len(files_to_search)
    
    for idx, file_path in enumerate(files_to_search, start=1):
        file_name = os.path.basename(file_path)
        push_log(log_queue, "INFO", f"[{idx}/{total_files}] Searching in: {file_name}")
        
        try:
            df = _read_table(file_path)
            if df.empty:
                continue
                
            # Search logic
            if match_type == "Exact match":
                if not case_sensitive:
                    lower_terms = set(t.lower() for t in search_terms)
                    # Check which cells exactly match any of the lower terms
                    mask = df.apply(lambda col: col.str.lower().isin(lower_terms)).any(axis=1)
                else:
                    mask = df.isin(search_terms).any(axis=1)
            else:
                # Partial match using Regex
                escaped_terms = [re.escape(term) for term in search_terms]
                pattern = '|'.join(escaped_terms)
                mask = df.apply(lambda col: col.str.contains(pattern, case=case_sensitive, regex=True, na=False)).any(axis=1)
                
            matched_df = df[mask].copy()
            
            if not matched_df.empty:
                # Add a provenance column so you know exactly which file the row came from
                matched_df.insert(0, "Source_File", file_name)
                all_matches.append(matched_df)
                push_log(log_queue, "SUCCESS", f"Found {len(matched_df)} matches in {file_name}")
                
        except Exception as e:
            push_log(log_queue, "ERROR", f"Failed to process {file_name}: {e}")
            
    # --- 4. Finalize and Export ---
    if not all_matches:
        push_log(log_queue, "WARNING", "No matches found in any of the provided files.")
        final_df = pd.DataFrame({"Result": ["No matches found for any provided terms."]})
    else:
        final_df = pd.concat(all_matches, ignore_index=True)
        push_log(log_queue, "SUCCESS", f"Search complete! Total rows found: {len(final_df)}")
        
    out_name = f"Multi_Search_Results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    out_path = os.path.join(outputpath, out_name)
    final_df.to_excel(out_path, index=False)
    
    return {"output_files": [out_path]}