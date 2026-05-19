import os
import re
import base64
from pathlib import Path

import pandas as pd

from core.io_utils import ensure_dir, zip_paths
from core.logging_utils import push_log

DESCRIPTION = "Decode Base64 content from uploaded spreadsheets or local TXT files inside folders."
BADGES = ["Folder scan", "TXT support", "Offline"]
ASSISTANT_HINT = "Use folder mode for local TXT files, or provide a CSV/XLSX with a Base64 column."
SUPPORTS_LOCAL_PATHS = True

PARAMS = [
    {"name": "mode", "type": "select", "label": "Input mode", "options": ["Spreadsheet upload", "Local folder TXT scan"], "default": "Local folder TXT scan"},
    {"name": "input_file", "type": "file", "label": "Spreadsheet file"},
    {"name": "base64_column", "type": "column", "label": "Base64 column", "source": "input_file"},
    {"name": "filename_column", "type": "column", "label": "Optional output filename column", "source": "input_file"},
    {"name": "local_folder", "type": "text", "label": "Local folder path"},
]

BASE64_PATTERN = re.compile(r"([A-Za-z0-9+/=\r\n]{40,})")


def _sanitize_name(name: str) -> str:
    bad = r'<>:"/\\|?*'
    for ch in bad:
        name = name.replace(ch, "_")
    return name.strip() or "decoded_file"


def _guess_extension(data: bytes) -> str:
    if data.startswith(b"%PDF"):
        return ".pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG"):
        return ".png"
    if data.startswith(b"PK\x03\x04"):
        return ".zip"
    return ".bin"


def _decode_to_file(b64_text: str, out_dir: str, desired_name: str):
    cleaned = "".join(str(b64_text).split())
    raw = base64.b64decode(cleaned, validate=False)
    ext = _guess_extension(raw)
    file_name = _sanitize_name(desired_name)
    if not os.path.splitext(file_name)[1]:
        file_name += ext
    out_path = os.path.join(out_dir, file_name)
    with open(out_path, "wb") as f:
        f.write(raw)
    return out_path, len(raw)


def _scan_txt_folder(folder_path: str, out_dir: str, log_queue):
    results = []
    output_files = []

    for root, _, files in os.walk(folder_path):
        folder_name = Path(root).name or "decoded_folder"
        folder_counter = 1  # Track parts across ALL files in this folder
        
        for file in files:
            if not file.lower().endswith(".txt"):
                continue

            full_path = os.path.join(root, file)
            try:
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()

                matches = BASE64_PATTERN.findall(text)
                if not matches:
                    results.append({
                        "source_file": full_path,
                        "status": "No Base64 match found",
                        "output_file": "",
                        "bytes_written": 0,
                    })
                    continue

                for match in matches:
                    # Uses the continuous counter for this folder
                    desired = f"{folder_name}_pt{folder_counter}"
                    out_path, byte_count = _decode_to_file(match, out_dir, desired)
                    output_files.append(out_path)
                    results.append({
                        "source_file": full_path,
                        "status": "Decoded",
                        "output_file": out_path,
                        "bytes_written": byte_count,
                    })
                    folder_counter += 1  # Increment for the next match in this folder

            except Exception as e:
                push_log(log_queue, "ERROR", f"Failed TXT decode for {full_path}: {e}")
                results.append({
                    "source_file": full_path,
                    "status": f"Failed: {e}",
                    "output_file": "",
                    "bytes_written": 0,
                })

    return results, output_files


def _spreadsheet_mode(input_file: str, base64_column: str, filename_column: str, out_dir: str, log_queue):
    ext = os.path.splitext(input_file)[1].lower()
    if ext == ".csv":
        df = pd.read_csv(input_file, dtype=str).fillna("")
    else:
        df = pd.read_excel(input_file, dtype=str).fillna("")

    results = []
    output_files = []

    for idx, row in df.iterrows():
        b64_text = str(row.get(base64_column, "")).strip()
        if not b64_text:
            results.append({
                "row_no": idx + 2,
                "status": "Blank Base64",
                "output_file": "",
                "bytes_written": 0,
            })
            continue

        desired_name = str(row.get(filename_column, "")).strip() if filename_column else ""
        desired_name = desired_name or f"decoded_row_{idx + 2}"

        try:
            out_path, byte_count = _decode_to_file(b64_text, out_dir, desired_name)
            output_files.append(out_path)
            results.append({
                "row_no": idx + 2,
                "status": "Decoded",
                "output_file": out_path,
                "bytes_written": byte_count,
            })
        except Exception as e:
            results.append({
                "row_no": idx + 2,
                "status": f"Failed: {e}",
                "output_file": "",
                "bytes_written": 0,
            })
            push_log(log_queue, "ERROR", f"Row {idx + 2} decode failed: {e}")

    return results, output_files


def run(inputpath, outputpath, kwargs, log_queue=None):
    log_queue = log_queue or []
    ensure_dir(outputpath)

    mode = kwargs.get("mode", "Local folder TXT scan")
    decoded_dir = os.path.join(outputpath, "decoded_files")
    ensure_dir(decoded_dir)

    if mode == "Local folder TXT scan":
        folder_path = kwargs.get("local_folder", "").strip()
        if not folder_path or not os.path.isdir(folder_path):
            raise ValueError("Please provide a valid local folder path for TXT scan mode.")
        results, output_files = _scan_txt_folder(folder_path, decoded_dir, log_queue)
    else:
        input_file = kwargs.get("input_file")
        base64_column = kwargs.get("base64_column", "").strip()
        filename_column = kwargs.get("filename_column", "").strip()
        if not input_file:
            raise ValueError("Please provide a spreadsheet file.")
        if not base64_column:
            raise ValueError("Please select the Base64 column.")
        results, output_files = _spreadsheet_mode(input_file, base64_column, filename_column, decoded_dir, log_queue)

    report_df = pd.DataFrame(results)
    report_path = os.path.join(outputpath, "base64_extraction_report.xlsx")
    report_df.to_excel(report_path, index=False)

    output_paths = [report_path]
    if output_files:
        zip_path = os.path.join(outputpath, "decoded_files.zip")
        zip_paths(output_files, zip_path)
        output_paths.append(zip_path)
        output_paths.extend(output_files)

    push_log(log_queue, "SUCCESS", f"Completed with {len(output_files)} decoded files")
    return {"output_files": output_paths}