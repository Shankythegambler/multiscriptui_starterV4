# High Scale Data Suite - Local Starter

## What is included
- Registry-based Streamlit UI
- Better descriptions, icons, and assistant hints
- Three working starter tools:
  - Excel / CSV Merger
  - Name Matcher
  - File Zipper

## Local run
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Suggested next migration order
1. Lookup Engine
2. Excel Multi-Search
3. Data Cleaning Utility
4. Name Cleaner
5. Advanced Status Profiler
6. Bulk File Downloader
7. Base64 Extractor
8. Education OCR
9. PDF Folder Merger
10. Mail Merge to PDF

## UI direction
- Keep the sidebar compact and descriptive.
- Use one icon per tool and 2-3 small badges.
- Keep assistant hint directly below the description.
- Always show a preview and a logs area.
- Avoid overloading the page with too many controls at once.
