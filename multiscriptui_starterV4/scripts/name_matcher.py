import os
import pandas as pd
from rapidfuzz.distance import JaroWinkler

from core.io_utils import ensure_dir
from core.logging_utils import push_log


DESCRIPTION = "Compare two name columns and generate similarity scores with notes."
BADGES = ["Fuzzy match", "Jaro-Winkler", "Review-ready"]
ASSISTANT_HINT = "Provide the file and select the two name columns to compare."
SUPPORTS_LOCAL_PATHS = True

PARAMS = [
    {"name": "input_file", "type": "file", "label": "Input file"},
    {"name": "col1", "type": "column", "label": "First name column", "source": "input_file"},
    {"name": "col2", "type": "column", "label": "Second name column", "source": "input_file"},
    {"name": "out_col", "type": "text", "label": "Output similarity column name", "default": "Similarity_Score"},
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


def _clean_name(value):
    if pd.isna(value):
        return ""
    s = str(value).strip().upper()
    for ch in [".", ",", ":", ";", "/", "\\", "-", "_", "\t"]:
        s = s.replace(ch, " ")
    return " ".join(s.split())


def _note(a, b, score):
    if not a and not b:
        return "Both blank"
    if not a or not b:
        return "One name missing"
    if score >= 98:
        return "Exact match"
    if score >= 90:
        return "Very strong match"
    if score >= 75:
        return "Strong match"
    if score >= 50:
        return "Partial match"
    return "Low similarity"


def run(inputpath, outputpath, kwargs, log_queue=None):
    log_queue = log_queue or []
    ensure_dir(outputpath)

    input_file = kwargs.get("input_file")
    col1 = kwargs.get("col1", "").strip()
    col2 = kwargs.get("col2", "").strip()
    out_col = kwargs.get("out_col", "Similarity_Score").strip() or "Similarity_Score"

    if not input_file:
        raise ValueError("Please provide the input file.")
    if not col1 or not col2:
        raise ValueError("Please select both name columns.")

    df = _read_file(input_file)

    if col1 not in df.columns or col2 not in df.columns:
        raise ValueError("Selected columns not found in the file.")

    scores = []
    notes = []

    for _, row in df.iterrows():
        a = _clean_name(row[col1])
        b = _clean_name(row[col2])
        score = round(JaroWinkler.normalized_similarity(a, b) * 100.0, 1) if a and b else 0.0
        scores.append(score if (a and b) else "")
        notes.append(_note(a, b, score))

    df[out_col] = scores
    df["Notes"] = notes

    output_file = os.path.join(outputpath, "name_matcher_output.xlsx")
    df.to_excel(output_file, index=False)

    push_log(log_queue, "SUCCESS", f"Processed {len(df)} rows")
    return {"output_files": [output_file]}