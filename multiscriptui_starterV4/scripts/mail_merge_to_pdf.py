from __future__ import annotations

from typing import Any, Dict

KEY = "mail_merge_to_pdf"
TITLE = "Mail Merge to PDF"
ICON = "📝"
CATEGORY = "Document Operations"
BADGES = ["Local-only", "Word dependency", "Planned"]
DESCRIPTION = "Mail merge starter placeholder. The production version depends on Microsoft Word or a document conversion pipeline and should stay local-only."
ASSISTANT_HINT = "This tool is registered as a placeholder so the final project structure stays complete during refactor."

PARAMS = []


def run(inputpath: str, outputpath: str, kwargs: Dict[str, Any], log_queue=None) -> Dict[str, Any]:
    raise NotImplementedError("Mail Merge to PDF is not enabled in this starter build. It should be implemented as a local-only tool.")
