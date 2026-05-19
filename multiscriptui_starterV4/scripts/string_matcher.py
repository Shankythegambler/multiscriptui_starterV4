import os
import time
from datetime import datetime
import pandas as pd

try:
    from rapidfuzz import process, fuzz, utils
except ImportError:
    raise ImportError("The 'rapidfuzz' library is required. Please install it by running: pip install rapidfuzz")

from core.logging_utils import push_log
from core.io_utils import ensure_dir

DESCRIPTION = "Fuzzy match a column of strings (e.g., OCR output) against a massive reference dump of 100k+ records."
BADGES = ["RapidFuzz", "100k+ Capacity", "Token Matching"]
ASSISTANT_HINT = "Upload your Input data and your Reference Dump. The tool maps the best match back to your input sheet instantly."
SUPPORTS_LOCAL_PATHS = False

PARAMS = [
    {"name": "input_file", "type": "file", "label": "1. Upload Input File (e.g., OCR Output)"},
    {"name": "input_column", "type": "column", "label": "Input Column to Match", "source": "input_file"},
    {"name": "dump_file", "type": "file", "label": "2. Upload Reference Dump File (The 100k+ list)"},
    {"name": "dump_column", "type": "column", "label": "Reference Column", "source": "dump_file"},
    {"name": "match_threshold", "type": "select", "label": "Minimum Match Score (0-100)", "options": ["50", "60", "70", "80", "90"], "default": "60"},
    {"name": "algorithm", "type": "select", "label": "Matching Algorithm", "options": ["Token Set Ratio (Best for partial/extra words)", "WRatio (Best overall balanced)"], "default": "Token Set Ratio (Best for partial/extra words)"}
]

def _read_table(fp: str) -> pd.DataFrame:
    """Reads CSV or Excel files securely."""
    if fp.lower().endswith(".csv"):
        return pd.read_csv(fp, dtype=str).fillna("")
    return pd.read_excel(fp, dtype=str).fillna("")

def run(inputpath, outputpath, kwargs, log_queue=None):
    log_queue = log_queue or []
    ensure_dir(outputpath)
    
    input_file = kwargs.get("input_file")
    input_column = kwargs.get("input_column", "").strip()
    dump_file = kwargs.get("dump_file")
    dump_column = kwargs.get("dump_column", "").strip()
    threshold = float(kwargs.get("match_threshold", "60"))
    algo_choice = kwargs.get("algorithm", "")

    # Select the right fuzzy scorer based on user choice
    if "Token Set Ratio" in algo_choice:
        scorer = fuzz.token_set_ratio
    else:
        scorer = fuzz.WRatio

    if not input_file or not dump_file:
        raise ValueError("Please upload BOTH the input file and the reference dump file.")
    if not input_column or not dump_column:
        raise ValueError("Please select the columns to match from both files.")

    # 1. Load Data
    push_log(log_queue, "INFO", "Loading Input and Dump datasets...")
    input_df = _read_table(input_file)
    dump_df = _read_table(dump_file)
    
    if input_column not in input_df.columns:
        raise ValueError(f"Input column '{input_column}' not found.")
    if dump_column not in dump_df.columns:
        raise ValueError(f"Dump column '{dump_column}' not found.")

    # 2. Extract Unique Values
    unique_queries = input_df[input_column].dropna().astype(str).unique()
    dump_choices = dump_df[dump_column].dropna().astype(str).unique().tolist()
    
    push_log(log_queue, "INFO", f"Matching {len(unique_queries)} unique inputs against {len(dump_choices)} reference records...")
    
    start_time = time.time()
    match_dictionary = {}
    total = len(unique_queries)

    # 3. Perform High-Speed Matching
    for idx, query in enumerate(unique_queries, start=1):
        if not query.strip():
            match_dictionary[query] = ("", 0.0)
            continue
            
        if idx % max(1, (total // 10)) == 0 or idx == total:
            push_log(log_queue, "INFO", f"Matching progress: {idx}/{total} complete...")

        match = process.extractOne(
            query,
            dump_choices,
            scorer=scorer,
            processor=utils.default_process,
            score_cutoff=threshold
        )
        
        if match:
            match_dictionary[query] = (match[0], round(match[1], 2))
        else:
            match_dictionary[query] = ("No Match Found", 0.0)

    elapsed = round(time.time() - start_time, 2)
    push_log(log_queue, "SUCCESS", f"Fuzzy matching completed in {elapsed} seconds!")

    # 4. Map the results back to the original Input DataFrame
    push_log(log_queue, "INFO", "Appending matched results to the input sheet...")
    
    def get_match_name(row_val):
        return match_dictionary.get(str(row_val), ("", 0.0))[0]

    def get_match_score(row_val):
        return match_dictionary.get(str(row_val), ("", 0.0))[1]

    col_idx = input_df.columns.get_loc(input_column) + 1
    
    input_df.insert(col_idx, "Best_String_Match", input_df[input_column].apply(get_match_name))
    input_df.insert(col_idx + 1, "Match_Score", input_df[input_column].apply(get_match_score))

    # 5. Export Results
    out_name = f"String_Matched_Data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    out_path = os.path.join(outputpath, out_name)
    
    input_df.to_excel(out_path, index=False)
    push_log(log_queue, "SUCCESS", f"Data saved! {len(input_df)} rows ready for download.")
    
    return {"output_files": [out_path]}