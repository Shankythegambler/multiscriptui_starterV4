from __future__ import annotations

import os
from typing import Any, Dict, Tuple

from core.io_utils import cleanup_workspace, create_temp_workspace, ensure_dir, save_uploaded_file


def resolve_uploaded_inputs(values: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any]]:
    workspace = create_temp_workspace()
    input_dir = os.path.join(workspace, "inputs")
    output_dir = os.path.join(workspace, "outputs")
    ensure_dir(input_dir)
    ensure_dir(output_dir)

    resolved: Dict[str, Any] = {}
    for key, value in values.items():
        if hasattr(value, "getbuffer") and hasattr(value, "name"):
            resolved[key] = save_uploaded_file(value, input_dir)
        elif isinstance(value, list) and value and hasattr(value[0], "getbuffer"):
            resolved[key] = [save_uploaded_file(v, input_dir) for v in value]
        else:
            resolved[key] = value

    return workspace, output_dir, resolved


def finalize_output_files(result: Dict[str, Any]) -> Dict[str, Any]:
    result.setdefault("output_files", [])
    return result


def cleanup_after_run(workspace: str) -> None:
    cleanup_workspace(workspace)
