# Academy Prequel V3 / Variant B runtime entrypoint.
# Railway runs `uvicorn app.server:app`; keep this file as the stable shim.

from __future__ import annotations

import os
from typing import Any

import app.variant_b_runtime as variant_b_runtime


def _compact_load_source_context(
    session_id: str,
    paths: list[str],
    max_total_chars: int | None = None,
    max_file_chars: int | None = None,
) -> list[dict[str, Any]]:
    """Keep character/source context, but stay under Groq Free TPM limits."""
    runtime = variant_b_runtime.runtime
    total_limit = max_total_chars or int(os.getenv("SOURCE_CONTEXT_MAX_CHARS", "6500"))
    file_limit = max_file_chars or int(os.getenv("SOURCE_CONTEXT_FILE_MAX_CHARS", "1000"))

    result: list[dict[str, Any]] = []
    total = 0
    for path in paths:
        if total >= total_limit:
            break
        try:
            text = runtime.read_project_or_runtime_file(path, session_id)
        except Exception:
            continue
        trimmed = text[:file_limit]
        remaining = total_limit - total
        if len(trimmed) > remaining:
            trimmed = trimmed[:remaining]
        if not trimmed.strip():
            continue
        result.append({"path": path, "content": trimmed})
        total += len(trimmed)
    return result


def _repair_toggle_quality_issues(scene_text: str) -> list[str]:
    """Allow disabling the second Groq call when free TPM is tight."""
    enabled = os.getenv("QUALITY_AUTO_REPAIR", "true").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return []
    return variant_b_runtime._original_scene_quality_issues(scene_text)


variant_b_runtime._load_source_context = _compact_load_source_context
if not hasattr(variant_b_runtime, "_original_scene_quality_issues"):
    variant_b_runtime._original_scene_quality_issues = variant_b_runtime._scene_quality_issues
variant_b_runtime._scene_quality_issues = _repair_toggle_quality_issues

variant_b_runtime.VARIANT_B_VERSION = "3.5.7-variant-b-groq-free-safe"
variant_b_runtime.app.version = variant_b_runtime.VARIANT_B_VERSION

app = variant_b_runtime.app
