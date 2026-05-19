from importlib import import_module

TOOLS = [
    ("🔍 Lookup Engine", "scripts.lookup_engine"),
    ("📊 Excel / CSV Merger", "scripts.excel_csv_merger"),
    ("🔎 Excel Multi-Search", "scripts.excel_multi_search"),
    ("🤝 Name Matcher", "scripts.name_matcher"),
("🤝 String Matcher", "scripts.string_matcher"),
    ("🗜️ File Zipper", "scripts.file_zipper"),
    ("⬇️ Bulk File Downloader", "scripts.bulk_file_downloader"),
    ("📝 Mail Merge to PDF", "scripts.mail_merge_to_pdf"),
    ("🧹 Data Cleaning Utility", "scripts.data_cleaning_utility"),
    ("🧼 Name Cleaner & Categorizer", "scripts.name_cleaner_categorizer"),
    ("📊 Advanced Status Profiler", "scripts.advanced_status_profiler"),
    ("🗃️ Base64 to File Extractor", "scripts.base64_extractor"),
    ("📄 PDF Folder Merger", "scripts.pdf_folder_merger"),
    ("📚 Mixed File PDF Merger", "scripts.mixed_file_pdf_merger"),
    ("📑 PDF to Excel", "scripts.pdf_to_excel"),
    ("🖼️ PDF to JPG", "scripts.pdf_to_jpg"),
    ("🎓 Education Documents OCR", "scripts.education_documents_ocr"),
    ("💼 Employment Documents OCR", "scripts.employment_documents_ocr"),
("🔄 JSON to Excel Converter", "scripts.json_to_excel_converter"),
("📄 Step 1: Batch Document OCR", "scripts.batch_ocr_engine"),
    ("🤖 Step 2: LLM Employment Extractor", "scripts.employment_llm_extractor"),
("🎓 Step 3 - LLM Education Extractor", "scripts.education_llm_extractor"),
("Code Generator","scripts.ollama_code_generator")
]

def _safe_load(module_path: str):
    try:
        mod = import_module(module_path)
        return {
            "ok": True,
            "module": mod,
            "func": getattr(mod, "run"),
            "desc": getattr(mod, "DESCRIPTION", ""),
            "params": getattr(mod, "PARAMS", []),
            "badges": getattr(mod, "BADGES", []),
            "assistant_hint": getattr(mod, "ASSISTANT_HINT", ""),
            "supports_local_paths": getattr(mod, "SUPPORTS_LOCAL_PATHS", True),
            "error": "",
        }
    except Exception as e:
        return {
            "ok": False,
            "module": None,
            "func": None,
            "desc": "",
            "params": [],
            "badges": [],
            "assistant_hint": "",
            "supports_local_paths": True,
            "error": str(e),
        }

CODE_REGISTRY = {}
for tool_name, module_path in TOOLS:
    CODE_REGISTRY[tool_name] = _safe_load(module_path)