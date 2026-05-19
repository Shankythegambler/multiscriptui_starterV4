import os
import json
import uuid
import re
from datetime import datetime
import pandas as pd

from core.logging_utils import push_log
from core.io_utils import ensure_dir

DESCRIPTION = "Extract and flatten JSON from a spreadsheet column, or convert raw JSON files into a structured Excel table."
BADGES = ["Spreadsheet Expansion", "Regex Salvage", "Auto-Flatten", "LLM-Safe"]
ASSISTANT_HINT = "Choose your mode. This tool safely ignores 'chatty' AI text, and salvages broken JSON or Markdown lists to prevent misalignment."
SUPPORTS_LOCAL_PATHS = False

PARAMS = [
    {"name": "mode", "type": "select", "label": "Input Mode", "options": ["Spreadsheet with JSON column", "Raw JSON file"], "default": "Spreadsheet with JSON column"},
    {"name": "input_file", "type": "file", "label": "Upload File (CSV, XLSX, or JSON)"},
    {"name": "json_column", "type": "column", "label": "JSON Column (Required for Spreadsheet mode)", "source": "input_file"},
    {"name": "record_path", "type": "text", "label": "Array Key (Optional: leave blank to auto-detect root)"},
    {"name": "generate_id", "type": "select", "label": "Generate missing Unique IDs?", "options": ["No", "Yes"], "default": "No"},
]

def _read_table(fp: str) -> pd.DataFrame:
    if fp.lower().endswith(".csv"):
        return pd.read_csv(fp)
    return pd.read_excel(fp)

def _extract_clean_json(text: str) -> str:
    """Finds the bounds of a JSON object/array, ignoring markdown and conversational text."""
    text = str(text).strip()
    if not text:
        return ""
        
    start_dict = text.find('{')
    start_list = text.find('[')
    
    if start_dict == -1 and start_list == -1:
        return "" 

    if start_dict != -1 and (start_list == -1 or start_dict < start_list):
        end_dict = text.rfind('}')
        if end_dict != -1:
            return text[start_dict:end_dict+1]
    elif start_list != -1:
        end_list = text.rfind(']')
        if end_list != -1:
            return text[start_list:end_list+1]
            
    return ""

def _salvage_broken_json(text: str) -> dict:
    """
    Aggressively hunts for "key": "value" pairs AND Markdown bullet-point lists 
    (e.g., * `key`: value) if the AI generated completely non-JSON output.
    """
    salvaged = {}
    
    # Pattern 1: Hunt for broken JSON format -> "key": "value" or "key": 123
    json_pattern = re.compile(r'"([a-zA-Z0-9_]+)"\s*:\s*(?:"([^"]*)"|([^,}\n]+))')
    for match in json_pattern.finditer(text):
        key = match.group(1)
        val_str = match.group(2)
        val_other = match.group(3)
        
        if val_str is not None:
            salvaged[key] = val_str.strip()
        elif val_other is not None:
            salvaged[key] = val_other.strip(' \r\n,"')

    # If we found JSON-style keys, return them.
    if salvaged:
        return salvaged

    # Pattern 2: Hunt for Markdown list format -> * `key`: value OR - **key**: value
    md_pattern = re.compile(r'[*+-]?\s*[`*]*([a-zA-Z0-9_]+)[`*]*\s*:\s*([^\n]+)')
    for match in md_pattern.finditer(text):
        key = match.group(1)
        val = match.group(2).strip(' \r\n,"\'')
        # Ensure we don't accidentally grab conversational sentences ending in a colon
        if len(key) < 50: 
            salvaged[key] = val
            
    return salvaged

def _flatten_json_data(data, record_path, log_queue, silent=False):
    """Safely normalizes JSON data into a DataFrame."""
    try:
        if record_path:
            keys = record_path.split('.')
            return pd.json_normalize(data, record_path=keys)
        else:
            if isinstance(data, dict):
                list_keys = [k for k, v in data.items() if isinstance(v, list)]
                if len(list_keys) == 1:
                    if not silent:
                        push_log(log_queue, "INFO", f"Auto-detected root array at key: '{list_keys[0]}'")
                    return pd.json_normalize(data, record_path=list_keys[0])
                else:
                    return pd.json_normalize(data)
            else:
                return pd.json_normalize(data)
    except Exception as e:
        if not silent:
            push_log(log_queue, "WARNING", f"Auto-flattening failed: {e}. Falling back to basic format.")
        return pd.DataFrame(data if isinstance(data, list) else [data])

def run(inputpath, outputpath, kwargs, log_queue=None):
    log_queue = log_queue or []
    ensure_dir(outputpath)
    
    mode = kwargs.get("mode", "Spreadsheet with JSON column")
    file_path = kwargs.get("input_file")
    json_column = kwargs.get("json_column", "").strip()
    record_path = kwargs.get("record_path", "").strip()
    generate_id = kwargs.get("generate_id", "No") == "Yes"
    
    if not file_path or not os.path.isfile(file_path):
        raise ValueError("Please upload a valid file.")
        
    final_df = pd.DataFrame()

    if mode == "Raw JSON file":
        push_log(log_queue, "INFO", "Loading raw JSON data...")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw_content = f.read()
                
            clean_content = _extract_clean_json(raw_content)
            if not clean_content:
                push_log(log_queue, "WARNING", "Valid JSON structure not found. Attempting regex salvage...")
                data = _salvage_broken_json(raw_content)
            else:
                try:
                    data = json.loads(clean_content)
                except json.JSONDecodeError:
                    push_log(log_queue, "WARNING", "JSON was structured but broken. Attempting regex salvage...")
                    data = _salvage_broken_json(clean_content)
                    
            final_df = _flatten_json_data(data, record_path, log_queue)
        except Exception as e:
            raise ValueError(f"Failed to read JSON. Error: {e}")

    else:
        # Spreadsheet Mode
        if not json_column:
            raise ValueError("Please select the column containing the JSON data.")
            
        push_log(log_queue, "INFO", "Loading spreadsheet...")
        source_df = _read_table(file_path)
        
        all_expanded_rows = []
        success_count = 0
        error_count = 0
        salvage_count = 0
        
        push_log(log_queue, "INFO", f"Extracting JSON from column: '{json_column}'")
        
        for idx, row in source_df.iterrows():
            orig_data = row.to_dict()
            raw_text = str(orig_data.pop(json_column, "")).strip()
            
            # Keep row as-is if cell is empty
            if not raw_text or raw_text.lower() in ['nan', 'none', 'null']:
                all_expanded_rows.append(orig_data)
                continue
                
            parsed_data = None
            is_salvaged = False
            
            try:
                clean_json_str = _extract_clean_json(raw_text)
                if not clean_json_str:
                    raise ValueError("No {...} structure found.")
                parsed_data = json.loads(clean_json_str)
            except Exception:
                # Fallback: Aggressively salvage whatever key-value pairs exist
                parsed_data = _salvage_broken_json(raw_text)
                is_salvaged = True

            if not parsed_data:
                # Complete failure to parse anything
                orig_data["JSON_Parse_Error"] = "Failed to parse or salvage any data."
                all_expanded_rows.append(orig_data)
                error_count += 1
                continue

            # Flatten the parsed data
            flat_df = _flatten_json_data(parsed_data, record_path, log_queue, silent=True)
            flat_records = flat_df.to_dict(orient="records")
            
            # Merge original row data with the new flattened JSON columns
            for record in flat_records:
                # Merge dicts (original data + parsed data). 
                merged_row = {**orig_data, **record}
                
                if is_salvaged:
                    merged_row["JSON_Parse_Note"] = "Data salvaged from broken text."
                    
                all_expanded_rows.append(merged_row)
                
            if is_salvaged:
                salvage_count += 1
            else:
                success_count += 1
        
        if salvage_count > 0:
            push_log(log_queue, "WARNING", f"Salvaged heavily broken JSON on {salvage_count} rows.")
        if error_count > 0:
            push_log(log_queue, "ERROR", f"Completely failed to parse JSON on {error_count} rows.")
            
        # Combine all dictionaries at once. This GUARANTEES columns align perfectly.
        final_df = pd.DataFrame(all_expanded_rows)
        
        # Reorder columns: Original columns first, followed by the new JSON columns
        orig_cols = [c for c in source_df.columns if c != json_column]
        new_cols = [c for c in final_df.columns if c not in orig_cols]
        final_df = final_df[orig_cols + new_cols]

    # Inject a system UUID if requested
    if generate_id:
        push_log(log_queue, "INFO", "Generating System UUIDs...")
        final_df.insert(0, "System_UUID", [str(uuid.uuid4()) for _ in range(len(final_df))])
        
    # EXCEL SAFETY FIX: Stringify lists/dicts so Excel doesn't crash
    for col in final_df.columns:
        if final_df[col].apply(lambda x: isinstance(x, (list, dict))).any():
            final_df[col] = final_df[col].apply(lambda x: json.dumps(x) if isinstance(x, (list, dict)) else x)
            
    out_name = f"flattened_json_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    out_path = os.path.join(outputpath, out_name)
    
    push_log(log_queue, "INFO", f"Saving {len(final_df)} rows to Excel...")
    final_df.to_excel(out_path, index=False)
    
    push_log(log_queue, "SUCCESS", "Conversion complete!")
    
    return {"output_files": [out_path]}