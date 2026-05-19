import os
import zipfile
from typing import List

import pandas as pd


TABULAR_EXTENSIONS = {".csv", ".xlsx", ".xls"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
PDF_EXTENSIONS = {".pdf"}


def ensure_dir(path: str) -> None:
    if path:
        os.makedirs(path, exist_ok=True)


def safe_file_exists(path: str) -> bool:
    return bool(path) and os.path.exists(path)


def get_file_ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def is_tabular_file(path: str) -> bool:
    return get_file_ext(path) in TABULAR_EXTENSIONS


def is_image_file(path: str) -> bool:
    return get_file_ext(path) in IMAGE_EXTENSIONS


def is_pdf_file(path: str) -> bool:
    return get_file_ext(path) in PDF_EXTENSIONS


def read_table(file_path: str, dtype=str) -> pd.DataFrame:
    ext = get_file_ext(file_path)
    if ext == ".csv":
        try:
            return pd.read_csv(file_path, dtype=dtype, encoding="utf-8", low_memory=False).fillna("")
        except UnicodeDecodeError:
            return pd.read_csv(file_path, dtype=dtype, encoding="latin-1", low_memory=False).fillna("")
    if ext in [".xlsx", ".xls"]:
        return pd.read_excel(file_path, dtype=dtype, engine="openpyxl").fillna("")
    raise ValueError(f"Unsupported or corrupted file: {file_path}")


def smart_read(file_path: str) -> pd.DataFrame:
    return read_table(file_path, dtype=str)


def get_headers_from_file(path: str) -> List[str]:
    ext = get_file_ext(path)
    if ext == ".csv":
        try:
            df = pd.read_csv(path, dtype=str, nrows=5, encoding="utf-8", low_memory=False).fillna("")
        except UnicodeDecodeError:
            df = pd.read_csv(path, dtype=str, nrows=5, encoding="latin-1", low_memory=False).fillna("")
        return [str(c) for c in df.columns]
    if ext in [".xlsx", ".xls"]:
        df = pd.read_excel(path, dtype=str, nrows=5, engine="openpyxl").fillna("")
        return [str(c) for c in df.columns]
    raise ValueError(f"Unsupported file format: {path}")


def preview_file(path: str, nrows: int = 5) -> pd.DataFrame:
    ext = get_file_ext(path)
    if ext == ".csv":
        try:
            return pd.read_csv(path, dtype=str, nrows=nrows, encoding="utf-8", low_memory=False).fillna("")
        except UnicodeDecodeError:
            return pd.read_csv(path, dtype=str, nrows=nrows, encoding="latin-1", low_memory=False).fillna("")
    if ext in [".xlsx", ".xls"]:
        return pd.read_excel(path, dtype=str, nrows=nrows, engine="openpyxl").fillna("")
    raise ValueError(f"Unsupported file format: {path}")


def save_uploaded_file(uploaded_file, target_dir: str) -> str:
    ensure_dir(target_dir)
    file_path = os.path.join(target_dir, uploaded_file.name)
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return file_path


def zip_paths(paths: List[str], zip_path: str) -> str:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in paths:
            if os.path.isfile(path):
                zf.write(path, arcname=os.path.basename(path))
    return zip_path


def write_df(df: pd.DataFrame, output_path: str) -> str:
    ext = get_file_ext(output_path)
    if ext == ".csv":
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
    elif ext in [".xlsx", ".xls"]:
        df.to_excel(output_path, index=False)
    else:
        raise ValueError(f"Unsupported output format: {output_path}")
    return output_path