import os
import shutil
import uuid
from pathlib import Path

import streamlit as st

# --- HARDCODED POPPLER PATH ---
POPPLER_PATH = r"C:\Users\shashank.singh\Desktop\Backup\Python Script\Release-24.08.0-0\poppler-24.08.0\Library\bin"
os.environ["PATH"] += os.pathsep + POPPLER_PATH
# ------------------------------

from registry import CODE_REGISTRY
from core.io_utils import (
    ensure_dir,
    save_uploaded_file,
    is_tabular_file,
)
from core.preview import (
    cached_preview_from_path,
    cached_headers_from_path,
    persist_uploaded_temp,
)

st.set_page_config(page_title="Data Utility Suite", page_icon="⚙️", layout="wide")

WORK_ROOT = os.path.join(os.getcwd(), "_runtime")
ensure_dir(WORK_ROOT)

# -------------------------------------------------
# THEME & ENHANCED UI STYLING
# -------------------------------------------------
st.markdown("""
<style>
    /* Global App Background */
    .stApp {
        background-color: #0d1117;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }

    /* Sidebar Styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1e3c72 0%, #2a5298 100%) !important;
        box-shadow: 2px 0 15px rgba(0,0,0,0.1);
    }
    [data-testid="stSidebar"] * {
        color: #ffffff !important;
    }
    [data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] > div,
    [data-testid="stSidebar"] .stTextInput input,
    [data-testid="stSidebar"] .stTextArea textarea {
        background: rgba(255, 255, 255, 0.1) !important;
        border: 1px solid rgba(255, 255, 255, 0.3) !important;
        border-radius: 8px;
    }
    [data-testid="stSidebar"] .stButton > button {
        background: rgba(255, 255, 255, 0.2) !important;
        border: 1px solid rgba(255, 255, 255, 0.5) !important;
        border-radius: 8px !important;
        font-weight: bold !important;
        transition: all 0.3s ease;
    }
    [data-testid="stSidebar"] .stButton > button:hover {
        background: rgba(255, 255, 255, 0.35) !important;
        transform: translateY(-2px);
    }

    /* Main Content Cards */
    .hero-card {
        background: linear-gradient(135deg, #d9ebd3 0%, #f0f4f8 100%);
        border-left: 11px solid #616a79;
        border-radius: 2rem;
        padding: 1rem;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
        margin-bottom: 25px;
        color:cornflowerblue;
    }
    .main-card {
        background: #307ac75e;
        border: 1px solid #b6afbe;
        border-radius: 12px;
        padding: 25px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.03);
        margin-bottom: 20px;
        color:rosybrown;
    }

    /* Badges */
    .badge {
        display: inline-block;
        background: #e3f2fd;
        color: #1565c0;
        border: 1px solid #bbdefb;
        border-radius: 20px;
        padding: 5px 12px;
        margin-right: 8px;
        margin-bottom: 8px;
        font-size: 13px;
        font-weight: bold;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    /* Status Boxes */
    .status-box {
        background: #ffffff;
        border-top: 4px solid #2a5298;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        height: 100%;
    }

    /* Tool Status Highlights */
    .tool-ok { color: #4caf50; font-weight: bold; }
    .tool-bad { color: #f44336; font-weight: bold; }
    
    /* Headers */
    h1, h2, h3 {
        color: #2c3e50;
    }
</style>
""", unsafe_allow_html=True)


# -------------------------------------------------
# SESSION STATE
# -------------------------------------------------
if "selected_tool" not in st.session_state:
    st.session_state.selected_tool = list(CODE_REGISTRY.keys())[0]
if "tool_outputs" not in st.session_state:
    st.session_state.tool_outputs = []
if "tool_logs" not in st.session_state:
    st.session_state.tool_logs = []
if "tool_status" not in st.session_state:
    st.session_state.tool_status = "Idle"
if "last_tool" not in st.session_state:
    st.session_state.last_tool = st.session_state.selected_tool
if "current_run_dir" not in st.session_state:
    st.session_state.current_run_dir = ""
if "status_message" not in st.session_state:
    st.session_state.status_message = ""

def clear_runtime_state(delete_files=True):
    run_dir = st.session_state.get("current_run_dir", "")
    st.session_state.tool_outputs = []
    st.session_state.tool_logs = []
    st.session_state.tool_status = "Idle"
    st.session_state.status_message = ""
    st.session_state.current_run_dir = ""

    if delete_files and run_dir and os.path.isdir(run_dir):
        try:
            shutil.rmtree(run_dir, ignore_errors=True)
        except Exception:
            pass

def get_headers_from_source(source_value):
    try:
        if not source_value:
            return []
        if hasattr(source_value, "getbuffer"):
            temp_path = persist_uploaded_temp(source_value)
            return cached_headers_from_path(temp_path)
        if isinstance(source_value, str) and os.path.isfile(source_value):
            return cached_headers_from_path(source_value)
        if isinstance(source_value, list) and source_value:
            first_item = source_value[0]
            if hasattr(first_item, "getbuffer"):
                temp_path = persist_uploaded_temp(first_item)
                return cached_headers_from_path(temp_path)
            if isinstance(first_item, str) and os.path.isfile(first_item):
                return cached_headers_from_path(first_item)
        return []
    except Exception:
        return []

def get_preview_source(resolved_values):
    for value in resolved_values.values():
        if hasattr(value, "name") and is_tabular_file(value.name):
            return value
        if isinstance(value, str) and os.path.isfile(value) and is_tabular_file(value):
            return value
        if isinstance(value, list) and value:
            first_item = value[0]
            if hasattr(first_item, "name") and is_tabular_file(first_item.name):
                return first_item
            if isinstance(first_item, str) and os.path.isfile(first_item) and is_tabular_file(first_item):
                return first_item
    return None

def resolve_single_file_input(param_name, label, help_text=""):
    source_mode = st.radio(f"{label} Data Source", ["Local path", "Upload"], horizontal=True, key=f"{param_name}_source_mode")
    if source_mode == "Local path":
        return st.text_input(label, help=help_text, key=f"{param_name}_local_path").strip()
    else:
        return st.file_uploader(label, help=help_text, key=f"{param_name}_upload")

def resolve_multi_file_input(param_name, label, help_text=""):
    source_mode = st.radio(f"{label} Data Source", ["Local paths", "Upload multiple"], horizontal=True, key=f"{param_name}_multi_source_mode")
    if source_mode == "Local paths":
        raw = st.text_area(label, help="Enter one full file path per line", key=f"{param_name}_local_paths")
        return [line.strip() for line in raw.splitlines() if line.strip()]
    else:
        return st.file_uploader(label, accept_multiple_files=True, help=help_text, key=f"{param_name}_uploads") or []

# -------------------------------------------------
# SIDEBAR NAVIGATION
# -------------------------------------------------
with st.sidebar:
    st.markdown("<h2 style='text-align: center;'>⚙️ Utility Suite</h2>", unsafe_allow_html=True)
    st.markdown("---")

    tool_names = list(CODE_REGISTRY.keys())
    selected_tool = st.selectbox("Select an Operation", tool_names, index=tool_names.index(st.session_state.selected_tool))
    st.session_state.selected_tool = selected_tool

    if st.session_state.last_tool != st.session_state.selected_tool:
        clear_runtime_state(delete_files=False)
        st.session_state.last_tool = st.session_state.selected_tool
        st.rerun()

    st.markdown("---")
    st.button("🔄 Clear Current Output", on_click=lambda: clear_runtime_state(delete_files=True), use_container_width=True)
    
    st.markdown("---")
    st.markdown("### System Diagnostics")
    for tool_name in tool_names:
        info = CODE_REGISTRY[tool_name]
        status_icon = "✅" if info["ok"] else "❌"
        status_class = "tool-ok" if info["ok"] else "tool-bad"
        st.markdown(f"<span class='{status_class}'>{status_icon} {tool_name}</span>", unsafe_allow_html=True)

tool_meta = CODE_REGISTRY[st.session_state.selected_tool]

# -------------------------------------------------
# MAIN INTERFACE
# -------------------------------------------------
left_pad, center, right_pad = st.columns([0.05, 0.9, 0.05])

with center:
    # Hero Section
    st.markdown(f"""
        <div class='hero-card'>
            <h1 style='margin-top:0; font-size: 32px;'>{st.session_state.selected_tool}</h1>
            <p style='color: #555; font-size: 16px; margin-bottom: 10px;'>{tool_meta['desc']}</p>
            <div>{"".join([f"<span class='badge'>{b}</span>" for b in tool_meta.get("badges", [])])}</div>
            <div style='margin-top:15px; padding: 10px; background: #eef2f5; border-radius: 8px; color: #333;'>
                <strong>💡 Quick Tip:</strong> {tool_meta.get('assistant_hint', 'Follow the parameter instructions below to execute the task.')}
            </div>
        </div>
    """, unsafe_allow_html=True)

    if st.session_state.status_message:
        st.info(st.session_state.status_message)

    if not tool_meta["ok"]:
        st.error(f"This tool is unavailable due to missing dependencies.\n\n**Error:**\n{tool_meta['error']}")
        st.stop()

    resolved_values = {}
    shown_source_hints = set()

    # Tool Parameters Section
    st.markdown("<div class='main-card'><h3>Configuration & Inputs</h3>", unsafe_allow_html=True)

    for param in tool_meta["params"]:
        p_name, p_type, p_label = param["name"], param["type"], param["label"]
        p_default, p_help, p_source = param.get("default", ""), param.get("help", ""), param.get("source")

        if p_type == "file":
            resolved_values[p_name] = resolve_single_file_input(p_name, p_label, p_help)
        elif p_type == "files":
            resolved_values[p_name] = resolve_multi_file_input(p_name, p_label, p_help)
        elif p_type == "text":
            resolved_values[p_name] = st.text_input(p_label, value=p_default, help=p_help, key=f"text_{p_name}")
        elif p_type == "textarea":
            resolved_values[p_name] = st.text_area(p_label, value=p_default, help=p_help, key=f"ta_{p_name}")
        elif p_type == "select":
            options = param.get("options", [])
            idx = options.index(p_default) if p_default in options else 0
            resolved_values[p_name] = st.selectbox(p_label, options, index=idx, help=p_help, key=f"sel_{p_name}")
        elif p_type == "multiselect":
            resolved_values[p_name] = st.multiselect(p_label, param.get("options", []), default=param.get("default", []), help=p_help, key=f"ms_{p_name}")
        elif p_type == "column":
            headers = get_headers_from_source(resolved_values.get(p_source))
            if not headers and p_source not in shown_source_hints:
                st.warning(f"Please provide '{p_source}' first to load columns.")
                shown_source_hints.add(p_source)
            resolved_values[p_name] = st.selectbox(p_label, [""] + headers, help=p_help, key=f"col_{p_name}")
        elif p_type == "columns":
            headers = get_headers_from_source(resolved_values.get(p_source))
            if not headers and p_source not in shown_source_hints:
                st.warning(f"Please provide '{p_source}' first to load columns.")
                shown_source_hints.add(p_source)
            resolved_values[p_name] = st.multiselect(p_label, headers, default=param.get("default", []), help=p_help, key=f"cols_{p_name}")

    st.markdown("<br>", unsafe_allow_html=True)
    run_clicked = st.button("🚀 Execute Tool", type="primary", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    # -------------------------------------------------
    # PREVIEW PANEL
    # -------------------------------------------------
    preview_target = get_preview_source(resolved_values)
    if preview_target:
        st.markdown("<div class='main-card'><h3>Data Preview</h3>", unsafe_allow_html=True)
        try:
            preview_path = persist_uploaded_temp(preview_target) if hasattr(preview_target, "getbuffer") else preview_target
            st.dataframe(cached_preview_from_path(preview_path, 5), use_container_width=True)
        except Exception as e:
            st.warning(f"Preview unavailable: {e}")
        st.markdown("</div>", unsafe_allow_html=True)

    # -------------------------------------------------
    # EXECUTION LOGIC
    # -------------------------------------------------
    if run_clicked:
        clear_runtime_state(delete_files=True)
        st.session_state.tool_status = "Running"
        
        # Remove invalid Windows characters (like colons) from the folder name
        safe_tool_name = st.session_state.selected_tool.replace(':', '-').replace(' ', '_')
        run_dir = os.path.join(WORK_ROOT, f"{safe_tool_name}_{str(uuid.uuid4())[:8]}")
        inputs_dir, outputs_dir = os.path.join(run_dir, "inputs"), os.path.join(run_dir, "outputs")
        ensure_dir(inputs_dir)
        ensure_dir(outputs_dir)

        final_kwargs = {}
        for key, val in resolved_values.items():
            if hasattr(val, "getbuffer"):
                final_kwargs[key] = save_uploaded_file(val, inputs_dir)
            elif isinstance(val, list) and val and hasattr(val[0], "getbuffer"):
                final_kwargs[key] = [save_uploaded_file(item, inputs_dir) for item in val]
            else:
                final_kwargs[key] = val

        logs = []
        try:
            with st.spinner('Processing... Please wait.'):
                result = tool_meta["func"](inputs_dir, outputs_dir, final_kwargs, log_queue=logs)
            st.session_state.tool_status = "Completed"
            st.session_state.tool_logs = logs
            st.session_state.tool_outputs = result.get("output_files", [])
            st.session_state.current_run_dir = run_dir
            st.session_state.status_message = "Execution completed successfully! 🎉"
        except Exception as e:
            st.session_state.tool_status = "Failed"
            logs.append({"timestamp": "", "level": "ERROR", "message": str(e)})
            st.session_state.tool_logs = logs
            st.session_state.current_run_dir = run_dir
            st.session_state.status_message = f"Execution failed: {e}"
        st.rerun()

    # -------------------------------------------------
    # RESULTS & LOGS PANEL
    # -------------------------------------------------
    if st.session_state.tool_status != "Idle":
        col_logs, col_downloads = st.columns([1.5, 1])

        with col_logs:
            st.markdown("<div class='status-box'>", unsafe_allow_html=True)
            st.markdown("<h3>Execution Logs</h3>", unsafe_allow_html=True)
            st.info(f"**Status:** {st.session_state.tool_status}")
            if st.session_state.tool_logs:
                with st.expander("View Detailed Logs", expanded=True):
                    for log in st.session_state.tool_logs[-100:]:
                        st.code(f"[{log.get('timestamp','')}] {log.get('level','INFO')}: {log.get('message','')}", language="bash")
            st.markdown("</div>", unsafe_allow_html=True)

        with col_downloads:
            st.markdown("<div class='status-box'>", unsafe_allow_html=True)
            st.markdown("<h3>Downloads</h3>", unsafe_allow_html=True)
            if st.session_state.tool_outputs:
                # Safely get unique paths in case tool_outputs contains duplicates
                unique_outputs = list(dict.fromkeys(st.session_state.tool_outputs))
                
                for i, out_path in enumerate(unique_outputs):
                    if os.path.isfile(out_path):
                        with open(out_path, "rb") as f:
                            st.download_button(
                                label=f"📥 Download {Path(out_path).name}",
                                data=f.read(),
                                file_name=Path(out_path).name,
                                key=f"dl_{i}_{out_path}", # Using 'i' ensures fully unique key 
                                use_container_width=True,
                            )
            else:
                st.write("No output files generated.")
            st.markdown("</div>", unsafe_allow_html=True)
