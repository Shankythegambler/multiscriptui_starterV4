import os
from pathlib import Path

import pandas as pd

from core.io_utils import ensure_dir
from core.logging_utils import push_log


DESCRIPTION = "Match input records against one or more lookup files and generate matched, unmatched, and consolidated outputs."
BADGES = ["Multi-file lookup", "Matched / unmatched", "Source tracking"]
ASSISTANT_HINT = "Provide one input file and one or more lookup files. Choose the match key columns and the lookup columns to bring back."
SUPPORTS_LOCAL_PATHS = True

PARAMS = [
    {"name": "input_file", "type": "file", "label": "Input file"},
    {"name": "lookup_files", "type": "files", "label": "Lookup files"},
    {"name": "input_key_col", "type": "column", "label": "Input key column", "source": "input_file"},
    {"name": "lookup_key_col", "type": "column", "label": "Lookup key column", "source": "lookup_files"},
    {"name": "fetch_cols", "type": "columns", "label": "Lookup columns to bring into output", "source": "lookup_files"},
    {"name": "key_type", "type": "select", "label": "Key type", "options": ["text", "mobile"], "default": "text"},
    {"name": "output_type", "type": "select", "label": "Output file type", "options": ["csv", "xlsx"], "default": "xlsx"},
]


def _read_file(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        try:
            return pd.read_csv(path, dtype=str, encoding="utf-8", low_memory=False).fillna("")
        except UnicodeDecodeError:
            return pd.read_csv(path, dtype=str, encoding="latin-1", low_memory=False).fillna("")
    if ext in [".xlsx", ".xls"]:
        return pd.read_excel(path, dtype=str).fillna("")
    raise ValueError(f"Unsupported file format: {path}")


def _normalize(series: pd.Series, key_type: str) -> pd.Series:
    s = series.fillna("").astype(str).str.strip()
    if key_type == "mobile":
        s = s.str.replace(r"\D", "", regex=True).str[-10:]
        s = s.where(s.str.len() >= 10, "")
    else:
        s = s.str.lower()
    return s


def _write_output(df: pd.DataFrame, output_path: str):
    ext = os.path.splitext(output_path)[1].lower()
    if ext == ".csv":
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
    else:
        df.to_excel(output_path, index=False)


def run(inputpath, outputpath, kwargs, log_queue=None):
    log_queue = log_queue or []
    ensure_dir(outputpath)

    input_file = kwargs.get("input_file")
    lookup_files = kwargs.get("lookup_files", [])
    input_key_col = kwargs.get("input_key_col", "").strip()
    lookup_key_col = kwargs.get("lookup_key_col", "").strip()
    fetch_cols = kwargs.get("fetch_cols", [])
    key_type = kwargs.get("key_type", "text")
    output_type = kwargs.get("output_type", "xlsx").lower()

    if not input_file:
        raise ValueError("Please provide the input file.")
    if not lookup_files:
        raise ValueError("Please provide at least one lookup file.")
    if not input_key_col:
        raise ValueError("Please select the input key column.")
    if not lookup_key_col:
        raise ValueError("Please select the lookup key column.")

    push_log(log_queue, "INFO", f"Loading input file: {os.path.basename(input_file)}")
    input_df = _read_file(input_file)

    if input_key_col not in input_df.columns:
        raise ValueError(f"Input key column '{input_key_col}' not found.")

    lookup_frames = []
    for lf in lookup_files:
        push_log(log_queue, "INFO", f"Loading lookup file: {os.path.basename(lf)}")
        df = _read_file(lf)

        if lookup_key_col not in df.columns:
            push_log(log_queue, "ERROR", f"Lookup key column '{lookup_key_col}' not found in {os.path.basename(lf)}")
            continue

        local_fetch_cols = [c for c in fetch_cols if c in df.columns]
        temp = df[[lookup_key_col] + local_fetch_cols].copy()
        temp["lookup_source_file"] = os.path.basename(lf)
        lookup_frames.append(temp)

    if not lookup_frames:
        raise ValueError("No valid lookup files could be processed.")

    lookup_df = pd.concat(lookup_frames, ignore_index=True).fillna("")
    input_df["_norm_key"] = _normalize(input_df[input_key_col], key_type)
    lookup_df["_norm_key"] = _normalize(lookup_df[lookup_key_col], key_type)

    lookup_df = lookup_df[lookup_df["_norm_key"] != ""].copy()
    lookup_df = lookup_df.drop_duplicates(subset=["_norm_key"], keep="first")

    result = input_df.merge(
        lookup_df.drop(columns=[lookup_key_col], errors="ignore"),
        on="_norm_key",
        how="left",
    )

    result["reason"] = ""
    result.loc[result["_norm_key"] == "", "reason"] = "INVALID_OR_BLANK_KEY"
    result.loc[(result["_norm_key"] != "") & (result["lookup_source_file"].fillna("") == ""), "reason"] = "NO_MATCH_FOUND"

    result["match_status"] = result["reason"].apply(lambda x: "MATCHED" if x == "" else "UNMATCHED")

    matched_df = result[result["match_status"] == "MATCHED"].copy()
    unmatched_df = result[result["match_status"] == "UNMATCHED"].copy()
    consolidated_df = result.copy()

    matched_df.drop(columns=["_norm_key"], inplace=True, errors="ignore")
    unmatched_df.drop(columns=["_norm_key"], inplace=True, errors="ignore")
    consolidated_df.drop(columns=["_norm_key"], inplace=True, errors="ignore")

    ext = ".csv" if output_type == "csv" else ".xlsx"
    matched_path = os.path.join(outputpath, f"lookup_engine_output_matched{ext}")
    unmatched_path = os.path.join(outputpath, f"lookup_engine_output_unmatched{ext}")
    consolidated_path = os.path.join(outputpath, f"lookup_engine_output_consolidated{ext}")

    _write_output(matched_df, matched_path)
    _write_output(unmatched_df, unmatched_path)
    _write_output(consolidated_df, consolidated_path)

    summary_df = pd.DataFrame([{
        "input_rows": len(input_df),
        "lookup_rows": len(lookup_df),
        "matched_rows": len(matched_df),
        "unmatched_rows": len(unmatched_df),
        "lookup_files_used": len(lookup_files),
        "key_type": key_type,
        "output_type": output_type,
    }])

    summary_path = os.path.join(outputpath, "lookup_engine_summary.xlsx")
    summary_df.to_excel(summary_path, index=False)

    push_log(log_queue, "SUCCESS", f"Matched: {len(matched_df)} | Unmatched: {len(unmatched_df)}")
    return {
        "output_files": [summary_path, matched_path, unmatched_path, consolidated_path]
    }