"""
Advanced Status Profiler
========================
Production-grade column profiling for large datasets (1Cr+ rows).

Key features
────────────
• Individual profiles   : summary stats, top-N values, narrative, data quality
• Auto pair cross-tabs  : every 2-column combination, automatically (e.g. Status × Region)
• Multi-column filters  : 14 operators, AND logic
• Filtered extraction   : dump matching rows to a sheet / CSV
• Output format choice  : Excel (styled) | CSV bundle | Both
                          → Ask for CSV when speed matters on large files
• Large-file safe       : chunked CSV reads, Parquet support
"""

import gc
import itertools
import json
import os
import time
import warnings
from datetime import datetime

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# PARAMS  (used by UI / caller frameworks)
# ─────────────────────────────────────────────────────────────────────────────
DESCRIPTION = (
    "Profile selected columns individually AND as combinations. "
    "Filter rows, extract matches, choose Excel or CSV output to save time."
)
BADGES = ["Individual profiles", "Auto pair cross-tabs", "Filters", "Extract", "Excel / CSV"]
ASSISTANT_HINT = (
    "Select 2+ columns to automatically get their individual profiles AND "
    "a Status x Region style cross-tab for every pair. "
    "Choose 'csv_only' output format for large files -- much faster than Excel."
)
SUPPORTS_LOCAL_PATHS = True

PARAMS = [
    {"name": "input_file",       "type": "file",    "label": "Input file (CSV / XLSX / Parquet)"},
    {"name": "summary_columns",  "type": "columns", "label": "Columns to profile",               "source": "input_file"},
    {"name": "group_by_column",  "type": "column",  "label": "Extra group-by column (optional)", "source": "input_file"},
    {"name": "top_n",            "type": "select",  "label": "Top N values per column",
     "options": ["5", "10", "20", "50"], "default": "10"},
    {"name": "filters",          "type": "json",    "label": "Filters (JSON list)",              "default": "[]"},
    {"name": "extract_filtered", "type": "bool",    "label": "Extract filtered rows?",           "default": "false"},
    # Output format: skip Excel to save significant time on 1Cr+ datasets
    {"name": "output_format",    "type": "select",  "label": "Output format",
     "options": ["excel_only", "csv_only", "both"], "default": "excel_only"},
    # Auto cross-tab every pair of selected columns
    {"name": "cross_tab_pairs",  "type": "bool",    "label": "Auto cross-tab every column pair?", "default": "true"},
    {"name": "chunk_size",       "type": "select",  "label": "Chunk size for large CSV",
     "options": ["100000", "250000", "500000", "1000000"], "default": "500000"},
]

# ─────────────────────────────────────────────────────────────────────────────
# STYLING
# ─────────────────────────────────────────────────────────────────────────────
HEADER_FILL  = PatternFill("solid", fgColor="1F3864")
ALT_FILL     = PatternFill("solid", fgColor="EEF2F7")
HEADER_FONT  = Font(name="Arial", bold=True, color="FFFFFF", size=10)
BODY_FONT    = Font(name="Arial", size=9)
TITLE_FONT   = Font(name="Arial", bold=True, size=13, color="1F3864")
CENTER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT_ALIGN   = Alignment(horizontal="left",   vertical="center", wrap_text=True)
THIN_BORDER  = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"),  bottom=Side(style="thin"),
)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _push(log_queue, level: str, msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    if isinstance(log_queue, list):
        log_queue.append({"level": level, "message": msg, "time": ts})
    print(f"[{ts}] [{level}] {msg}")

def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def _fmt(n) -> str:
    return f"{n:,}"

def _pct(num, denom) -> float:
    return round((num / denom) * 100, 2) if denom else 0.0

# ─────────────────────────────────────────────────────────────────────────────
# FILE READING  (chunked for large CSV)
# ─────────────────────────────────────────────────────────────────────────────

def _read_file(path: str, chunk_size: int = 500_000) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".parquet":
        return pd.read_parquet(path, dtype_backend="numpy_nullable")
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path, dtype=str).fillna("")
    if ext == ".csv":
        enc = "utf-8"
        try:
            pd.read_csv(path, nrows=2, encoding="utf-8")
        except UnicodeDecodeError:
            enc = "latin-1"
        if os.path.getsize(path) < 50 * 1024 * 1024:
            return pd.read_csv(path, dtype=str, encoding=enc, low_memory=False).fillna("")
        chunks = []
        for chunk in pd.read_csv(path, dtype=str, encoding=enc,
                                  low_memory=False, chunksize=chunk_size):
            chunks.append(chunk.fillna(""))
        df = pd.concat(chunks, ignore_index=True)
        del chunks
        gc.collect()
        return df
    raise ValueError(f"Unsupported file format: {ext}")

# ─────────────────────────────────────────────────────────────────────────────
# FILTER ENGINE
# ─────────────────────────────────────────────────────────────────────────────

OPERATORS = {
    "==":           lambda s, v: s == v,
    "!=":           lambda s, v: s != v,
    "contains":     lambda s, v: s.str.contains(v, case=False, na=False, regex=False),
    "not_contains": lambda s, v: ~s.str.contains(v, case=False, na=False, regex=False),
    "startswith":   lambda s, v: s.str.startswith(v, na=False),
    "endswith":     lambda s, v: s.str.endswith(v, na=False),
    "regex":        lambda s, v: s.str.contains(v, case=False, na=False, regex=True),
    "in":           lambda s, v: s.isin([x.strip() for x in v.split(",")]),
    "not_in":       lambda s, v: ~s.isin([x.strip() for x in v.split(",")]),
    "blank":        lambda s, v: s.str.strip() == "",
    "not_blank":    lambda s, v: s.str.strip() != "",
    ">":            lambda s, v: pd.to_numeric(s, errors="coerce") > float(v),
    "<":            lambda s, v: pd.to_numeric(s, errors="coerce") < float(v),
    ">=":           lambda s, v: pd.to_numeric(s, errors="coerce") >= float(v),
    "<=":           lambda s, v: pd.to_numeric(s, errors="coerce") <= float(v),
}

def _apply_filters(df: pd.DataFrame, filters: list) -> tuple:
    if not filters:
        return df, "No filters applied"
    mask  = pd.Series(True, index=df.index)
    parts = []
    for f in filters:
        col = f.get("column", "").strip()
        op  = f.get("operator", "==").strip()
        val = str(f.get("value", "")).strip()
        if col not in df.columns:
            raise ValueError(f"Filter column '{col}' not found.")
        if op not in OPERATORS:
            raise ValueError(f"Unknown operator '{op}'. Valid: {list(OPERATORS)}")
        mask &= OPERATORS[op](df[col].fillna("").astype(str), val)
        parts.append(f"[{col} {op} '{val}']")
    return df[mask].copy(), " AND ".join(parts)

# ─────────────────────────────────────────────────────────────────────────────
# INDIVIDUAL COLUMN PROFILE
# ─────────────────────────────────────────────────────────────────────────────

def _profile_column(df: pd.DataFrame, col: str, n: int, top_n: int) -> dict:
    s         = df[col].fillna("").astype(str).str.strip()
    blank     = int((s == "").sum())
    non_blank = n - blank
    distinct  = int(s[s != ""].nunique())
    vc        = s[s != ""].value_counts(dropna=False)

    mv1 = vc.index[0]     if len(vc) > 0 else ""
    mc1 = int(vc.iloc[0]) if len(vc) > 0 else 0
    mv2 = vc.index[1]     if len(vc) > 1 else ""
    mc2 = int(vc.iloc[1]) if len(vc) > 1 else 0

    top_values = [
        {"rank": r, "value": val, "count": int(cnt),
         "percent": _pct(cnt, n), "cum_pct": _pct(vc.iloc[:r].sum(), n)}
        for r, (val, cnt) in enumerate(vc.head(top_n).items(), start=1)
    ]
    cov = _pct(non_blank, n)
    narrative = (
        f"Column '{col}' has {_fmt(n)} total rows. "
        f"{_fmt(blank)} blank ({_pct(blank, n):.1f}%), "
        f"{_fmt(non_blank)} populated ({cov:.1f}% coverage), "
        f"{_fmt(distinct)} distinct non-blank values. "
        f"Most common: '{mv1}' ({_fmt(mc1)}, {_pct(mc1, n):.1f}%)."
        + (f" 2nd: '{mv2}' ({_fmt(mc2)}, {_pct(mc2, n):.1f}%)." if mv2 else "")
    )
    return {
        "summary": {
            "column_name": col,
            "total_rows": n, "blank_rows": blank, "blank_pct": _pct(blank, n),
            "non_blank_rows": non_blank, "coverage_pct": cov,
            "distinct_non_blank_values": distinct,
            "most_common_value": mv1, "most_common_count": mc1,
            "most_common_pct": _pct(mc1, n),
            "second_common_value": mv2, "second_common_count": mc2,
            "second_common_pct": _pct(mc2, n),
            "cardinality_flag": "HIGH" if distinct > 10_000 else "MEDIUM" if distinct > 100 else "LOW",
        },
        "top_values": top_values,
        "narrative": narrative,
    }

# ─────────────────────────────────────────────────────────────────────────────
# PAIR CROSS-TAB  e.g. Status x Region
# ─────────────────────────────────────────────────────────────────────────────

def _pair_crosstab(df: pd.DataFrame, col_a: str, col_b: str, n: int) -> pd.DataFrame:
    """
    Returns every (col_a_value, col_b_value) combination with:
      count | pct_of_total | pct_within_col_a | pct_within_col_b

    Example with Status & Region selected:
      pair=Status x Region | Status=Active | Region=North | count=1200
      pct_of_total=12.0% | pct_within_Status=40.0% | pct_within_Region=30.0%
    """
    tmp = df.assign(**{
        col_a: df[col_a].fillna("").astype(str).str.strip(),
        col_b: df[col_b].fillna("").astype(str).str.strip(),
    })
    grp = tmp.groupby([col_a, col_b], dropna=False).size().reset_index(name="count")
    grp["pct_of_total"]     = grp["count"].apply(lambda x: _pct(x, n))
    grp["pct_within_col_a"] = (grp["count"] / grp.groupby(col_a)["count"].transform("sum") * 100).round(2)
    grp["pct_within_col_b"] = (grp["count"] / grp.groupby(col_b)["count"].transform("sum") * 100).round(2)
    grp.insert(0, "pair", f"{col_a} x {col_b}")
    return grp.sort_values("count", ascending=False).reset_index(drop=True)

# ─────────────────────────────────────────────────────────────────────────────
# DATA QUALITY
# ─────────────────────────────────────────────────────────────────────────────

def _data_quality(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    rows = []
    for col in cols:
        s      = df[col].fillna("").astype(str).str.strip()
        nb     = s[s != ""]
        num_s  = pd.to_numeric(nb, errors="coerce")
        is_num = num_s.notna().sum() / len(nb) > 0.9 if len(nb) else False
        rows.append({
            "column":                col,
            "inferred_type":         "Numeric" if is_num else "Text / Categorical",
            "total_rows":            len(s),
            "blank_rows":            int((s == "").sum()),
            "duplicate_rows":        int(s.duplicated(keep=False).sum()),
            "unique_rows":           int(s.nunique()),
            "max_length":            int(s.str.len().max()) if len(s) else 0,
            "min_length":            int(nb.str.len().min()) if len(nb) else 0,
            "numeric_outliers_1_99": (
                int(((num_s < num_s.quantile(0.01)) | (num_s > num_s.quantile(0.99))).sum())
                if is_num and len(num_s.dropna()) > 10 else "N/A"
            ),
        })
    return pd.DataFrame(rows)

# ─────────────────────────────────────────────────────────────────────────────
# EXCEL OUTPUT
# ─────────────────────────────────────────────────────────────────────────────

SHEET_WIDTHS = {
    "run_info":       [30, 65],
    "column_summary": [22, 12, 10, 10, 14, 10, 24, 18, 12, 24, 18, 12, 12],
    "top_values":     [22, 8, 28, 12, 10, 10],
    "narrative":      [22, 95],
    "pair_crosstabs": [26, 22, 22, 14, 14, 18, 18],
    "group_by_cross": [20, 20, 20, 14, 10],
    "filter_counts":  [22, 28, 14, 10],
    "data_quality":   [22, 20, 12, 12, 14, 12, 12, 12, 20],
}

def _style_sheet(ws, widths: list):
    for cell in ws[1]:
        cell.font = HEADER_FONT; cell.fill = HEADER_FILL
        cell.alignment = CENTER_ALIGN; cell.border = THIN_BORDER
    for ri, row in enumerate(ws.iter_rows(min_row=2), start=2):
        fill = ALT_FILL if ri % 2 == 0 else None
        for cell in row:
            cell.font = BODY_FONT; cell.alignment = LEFT_ALIGN
            cell.border = THIN_BORDER
            if fill:
                cell.fill = fill
    if widths:
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
    else:
        for col_cells in ws.columns:
            w = max((len(str(c.value or "")) for c in col_cells), default=10)
            ws.column_dimensions[get_column_letter(col_cells[0].column)].width = min(w + 2, 40)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

def _add_title(ws, title: str):
    ws.insert_rows(1)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ws.max_column)
    c = ws.cell(row=1, column=1, value=title)
    c.font = TITLE_FONT; c.alignment = CENTER_ALIGN
    c.fill = PatternFill("solid", fgColor="D6E4F0")

def _write_excel(outputpath: str, ts: str, tables: dict, log_queue) -> str:
    path = os.path.join(outputpath, f"advanced_status_profile_{ts}.xlsx")
    _push(log_queue, "INFO", "Writing Excel…")
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet, df in tables.items():
            if df is not None and not df.empty:
                df.to_excel(writer, sheet_name=sheet, index=False)
    _push(log_queue, "INFO", "Applying styling…")
    wb = load_workbook(path)
    for sname in wb.sheetnames:
        ws = wb[sname]
        if ws.max_row < 2:
            continue
        _style_sheet(ws, SHEET_WIDTHS.get(sname, []))
        _add_title(ws, f"Advanced Status Profiler -- {sname.replace('_', ' ').title()}")
    wb.save(path)
    return path

# ─────────────────────────────────────────────────────────────────────────────
# CSV OUTPUT  (fast, no styling overhead)
# ─────────────────────────────────────────────────────────────────────────────

def _write_csv_bundle(outputpath: str, ts: str, tables: dict) -> list:
    folder = os.path.join(outputpath, f"profile_csvs_{ts}")
    os.makedirs(folder, exist_ok=True)
    files = []
    for name, df in tables.items():
        if df is not None and not df.empty:
            p = os.path.join(folder, f"{name}.csv")
            df.to_csv(p, index=False)
            files.append(p)
    return files

# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def run(inputpath: str, outputpath: str, kwargs: dict, log_queue=None):
    log_queue = log_queue or []
    t0 = time.time()
    _ensure_dir(outputpath)

    # params
    input_file       = kwargs.get("input_file", "")
    summary_columns  = kwargs.get("summary_columns", [])
    group_by_column  = kwargs.get("group_by_column", "").strip()
    top_n            = int(kwargs.get("top_n", "10"))
    filters          = kwargs.get("filters", [])
    extract_filtered = str(kwargs.get("extract_filtered", "false")).lower() == "true"
    output_format    = kwargs.get("output_format", "excel_only")
    cross_tab_pairs  = str(kwargs.get("cross_tab_pairs", "true")).lower() == "true"
    chunk_size       = int(kwargs.get("chunk_size", "500000"))

    if isinstance(filters, str):
        filters = json.loads(filters) if filters.strip() else []

    if not input_file:
        raise ValueError("Please provide the input file.")
    if not summary_columns:
        raise ValueError("Please select at least one column to profile.")

    # read
    _push(log_queue, "INFO", f"Reading: {input_file}")
    df = _read_file(input_file, chunk_size)
    total_rows = len(df)
    _push(log_queue, "INFO", f"Loaded {_fmt(total_rows)} rows x {df.shape[1]} columns")

    # validate
    missing = [c for c in summary_columns if c not in df.columns]
    if missing:
        raise ValueError(f"Columns not found in file: {missing}")
    if group_by_column and group_by_column not in df.columns:
        raise ValueError(f"Group-by column '{group_by_column}' not found.")

    # filter
    _push(log_queue, "INFO", f"Applying {len(filters)} filter(s)...")
    df_f, filters_desc = _apply_filters(df, filters)
    n_f = len(df_f)
    _push(log_queue, "INFO",
          f"Rows after filter: {_fmt(n_f)} / {_fmt(total_rows)} ({_pct(n_f, total_rows):.1f}%)")

    # individual profiles
    summary_rows, top_value_rows, narrative_rows = [], [], []
    for col in summary_columns:
        _push(log_queue, "INFO", f"Profiling '{col}'...")
        res = _profile_column(df_f, col, n_f, top_n)
        summary_rows.append(res["summary"])
        for tv in res["top_values"]:
            top_value_rows.append({"column_name": col, **tv})
        narrative_rows.append({"column_name": col, "narrative": res["narrative"]})

    # pair cross-tabs -- every 2-column combination automatically
    #
    # With Status + Region selected you get:
    #   Status profile (individual)
    #   Region profile (individual)
    #   Status x Region cross-tab (count, % of total, % within Status, % within Region)
    #
    pair_frames = []
    if cross_tab_pairs and len(summary_columns) >= 2:
        pairs = list(itertools.combinations(summary_columns, 2))
        _push(log_queue, "INFO",
              f"Building {len(pairs)} pair cross-tab(s): " +
              ", ".join(f"{a} x {b}" for a, b in pairs))
        for ca, cb in pairs:
            pair_frames.append(_pair_crosstab(df_f, ca, cb, n_f))
    pair_df = pd.concat(pair_frames, ignore_index=True) if pair_frames else pd.DataFrame()

    # optional extra group-by
    grp_frames = []
    if group_by_column:
        for col in summary_columns:
            tmp = (df_f.groupby([group_by_column, col], dropna=False)
                   .size().reset_index(name="count"))
            tmp["pct_of_total"]    = tmp["count"].apply(lambda x: _pct(x, n_f))
            tmp["profiled_column"] = col
            grp_frames.append(tmp)
    grp_df = pd.concat(grp_frames, ignore_index=True) if grp_frames else pd.DataFrame()

    # filter value counts
    fc_rows = []
    for col in summary_columns:
        vc = df_f[col].fillna("").astype(str).str.strip().value_counts(dropna=False)
        for val, cnt in vc.items():
            fc_rows.append({"column": col, "value": val,
                            "count": int(cnt), "percent": _pct(cnt, n_f)})

    # metadata
    ts_str  = datetime.now().strftime("%Y%m%d_%H%M%S")
    elapsed = round(time.time() - t0, 1)
    meta    = pd.DataFrame([
        ["Generated at",            datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ["Input file",              input_file],
        ["Total rows (raw)",        total_rows],
        ["Filtered rows",           n_f],
        ["Filter applied",          filters_desc],
        ["Columns profiled",        ", ".join(summary_columns)],
        ["Pair cross-tabs built",   f"{len(pair_frames)} pair(s)" if pair_frames else "None/disabled"],
        ["Group-by column",         group_by_column or "--"],
        ["Top N",                   top_n],
        ["Output format",           output_format],
        ["Extract filtered rows",   str(extract_filtered)],
        ["Run time so far (sec)",   elapsed],
    ], columns=["Parameter", "Value"])

    # assemble
    tables = {
        "run_info":       meta,
        "column_summary": pd.DataFrame(summary_rows),
        "top_values":     pd.DataFrame(top_value_rows),
        "narrative":      pd.DataFrame(narrative_rows),
        "pair_crosstabs": pair_df,
        "group_by_cross": grp_df,
        "filter_counts":  pd.DataFrame(fc_rows),
        "data_quality":   _data_quality(df_f, summary_columns),
        "source_sample":  df_f.head(50_000),
    }
    if extract_filtered:
        _push(log_queue, "INFO", "Attaching extracted rows (capped at 1M)...")
        tables["extracted_rows"] = df_f.iloc[:1_000_000]

    # write
    output_files = []
    if output_format in ("excel_only", "both"):
        xl = _write_excel(outputpath, ts_str, tables, log_queue)
        output_files.append(xl)
        _push(log_queue, "SUCCESS", f"Excel -> {xl}")
    if output_format in ("csv_only", "both"):
        csvs = _write_csv_bundle(outputpath, ts_str, tables)
        output_files.extend(csvs)
        _push(log_queue, "SUCCESS", f"CSV bundle -> {len(csvs)} file(s)")

    elapsed = round(time.time() - t0, 1)
    _push(log_queue, "SUCCESS",
          f"Done in {elapsed}s | {len(summary_columns)} col(s) | "
          f"{_fmt(n_f)} rows | {len(pair_frames)} pair cross-tab(s)")

    return {"output_files": output_files}

# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Advanced Status Profiler")
    p.add_argument("input_file")
    p.add_argument("--cols",       nargs="+", required=True,  help="Columns to profile")
    p.add_argument("--group_by",   default="",                help="Extra group-by column")
    p.add_argument("--top_n",      default="10")
    p.add_argument("--filters",    default="[]",
                   help='e.g. \'[{"column":"Status","operator":"==","value":"Active"}]\'')
    p.add_argument("--extract",    action="store_true",        help="Extract filtered rows")
    p.add_argument("--format",     default="excel_only",
                   choices=["excel_only", "csv_only", "both"])
    p.add_argument("--no_pairs",   action="store_true",        help="Disable auto pair cross-tabs")
    p.add_argument("--outputpath", default="./output")
    p.add_argument("--chunk_size", default="500000")
    args = p.parse_args()

    result = run(
        inputpath="",
        outputpath=args.outputpath,
        kwargs={
            "input_file":       args.input_file,
            "summary_columns":  args.cols,
            "group_by_column":  args.group_by,
            "top_n":            args.top_n,
            "filters":          json.loads(args.filters),
            "extract_filtered": str(args.extract).lower(),
            "output_format":    args.format,
            "cross_tab_pairs":  str(not args.no_pairs).lower(),
            "chunk_size":       args.chunk_size,
        },
    )
    print("\nOutput files:")
    for f in result["output_files"]:
        print(" ", f)
