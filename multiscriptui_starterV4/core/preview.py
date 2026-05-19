import hashlib
import os
import tempfile

import pandas as pd
import streamlit as st

from core.io_utils import preview_file, save_uploaded_file, is_tabular_file


@st.cache_data(show_spinner=False)
def cached_preview_from_path(path: str, nrows: int = 5) -> pd.DataFrame:
    return preview_file(path, nrows=nrows)


@st.cache_data(show_spinner=False)
def cached_headers_from_path(path: str):
    from core.io_utils import get_headers_from_file
    return get_headers_from_file(path)


def persist_uploaded_temp(uploaded_file) -> str:
    suffix = os.path.splitext(uploaded_file.name)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getbuffer())
        return tmp.name


def can_preview_uploaded(uploaded_file) -> bool:
    return bool(uploaded_file) and is_tabular_file(uploaded_file.name)


def stable_key_for_upload(uploaded_file) -> str:
    return hashlib.md5(uploaded_file.getvalue()).hexdigest()