# Academy Prequel V3 / Variant B runtime entrypoint.
# Railway runs `uvicorn app.server:app`; keep this file as the stable shim.

from __future__ import annotations

import os
from typing import Any


def _env_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _looks_like_local_base_url() -> bool:
    base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL", "").lower()
    return "127.0.0.1" in base_url or "localhost" in base_url or "lmstudio" in base_url


LOCAL_LM_STUDIO_MODE = _env_enabled("LOCAL_LM_STUDIO_MODE") or _looks_like_local_base_url()

if LOCAL_LM_STUDIO_MODE:
    # Safe local defaults for LM Studio / qwen3-8b. setdefault keeps explicit env
    # values and preserves Railway/Groq behaviour when the flag/base_url is absent.
    os.environ.setdefault("OPENAI_COMPATIBLE_JSON_MODE", "false")
    os.environ.setdefault("SOURCE_CONTEXT_MAX_CHARS", "3000")
    os.environ.setdefault("SOURCE_CONTEXT_FILE_MAX_CHARS", "500")
    os.environ.setdefault("QUALITY_AUTO_REPAIR", "false")
    os.environ.setdefault("OPENAI_COMPATIBLE_MAX_TOKENS", "600")
    os.environ.setdefault("OPENAI_COMPATIBLE_TIMEOUT", "240")

import app.variant_b_runtime as variant_b_runtime


def _compact_load_source_context(
    session_id: str,
    paths: list[str],
    max_total_chars: int | None = None,
    max_file_chars: int | None = None,
) -> list[dict[str, Any]]:
    """Keep source context, but allow compact LM Studio defaults."""
    runtime = variant_b_runtime.runtime
    total_default = "3000" if LOCAL_LM_STUDIO_MODE else "6500"
    file_default = "500" if LOCAL_LM_STUDIO_MODE else "1000"
    total_limit = max_total_chars or int(os.getenv("SOURCE_CONTEXT_MAX_CHARS", total_default))
    file_limit = max_file_chars or int(os.getenv("SOURCE_CONTEXT_FILE_MAX_CHARS", file_default))

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


def _safe_build_prompt_bundle(session_id: str, user_input: str, mode: str):
    """Remove copyable examples; keep rules as constraints only."""
    bundle, required_files = variant_b_runtime._original_build_prompt_bundle(session_id, user_input, mode)
    bundle.pop("style_micro_example", None)
    bundle["style_generation_constraints"] = {
        "do_not_copy_prompt_text": True,
        "pov_filter": "Describe people only through what Akira can observe and judge. No objective labels like charismatic/confident/interesting.",
        "dialogue_format": "Descriptions/remarks in italics. Character speech as **Name** — text. Do not write Akira speech unless user wrote it.",
        "action_weight_rule": "Each action option must include a distinct consequence weight: risk, information, social pressure, speed, relationship, or control.",
        "thought_rule": "Akira thoughts must be concrete working assessments, not philosophy or friendly curiosity.",
    }
    bundle["forbidden_generic_phrases"] = list(
        dict.fromkeys(
            list(bundle.get("forbidden_generic_phrases", []))
            + [
                "Асфальт ещё держал ночную воду",
                "Мяч ударился о сетку слишком громко для случайности",
                "Ливия хотела сказать что-то едкое",
                "Акира оценила проход, людей, расстояние до двери",
                "харизматичный рыжий",
                "рыжий и харизматичный",
                "Райден кажется интересным",
                "Вопрос был, как Акира решила бы",
            ]
        )
    )
    return bundle, required_files


def _repair_toggle_quality_issues(scene_text: str) -> list[str]:
    """Allow disabling the second model call when local context/latency is tight."""
    enabled = os.getenv("QUALITY_AUTO_REPAIR", "true").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return []
    issues = variant_b_runtime._original_scene_quality_issues(scene_text)
    lower = scene_text.lower()
    copied_example_bits = [
        "асфальт ещё держал ночную воду",
        "мяч ударился о сетку слишком громко для случайности",
        "ливия хотела сказать что-то едкое",
        "акира оценила проход, людей, расстояние до двери",
    ]
    for phrase in copied_example_bits:
        if phrase in lower:
            issues.append(f"copied prompt micro-example: {phrase}")
    if "вопрос был, как акира" in lower:
        issues.append("external author framing instead of playable choice")
    if "✦ что можно сделать" not in lower:
        issues.append("missing playable action block")
    return issues[:12]


variant_b_runtime._load_source_context = _compact_load_source_context

if not hasattr(variant_b_runtime, "_original_build_prompt_bundle"):
    variant_b_runtime._original_build_prompt_bundle = variant_b_runtime._build_prompt_bundle
variant_b_runtime._build_prompt_bundle = _safe_build_prompt_bundle

if not hasattr(variant_b_runtime, "_original_scene_quality_issues"):
    variant_b_runtime._original_scene_quality_issues = variant_b_runtime._scene_quality_issues
variant_b_runtime._scene_quality_issues = _repair_toggle_quality_issues

variant_b_runtime.VARIANT_B_VERSION = "3.5.9-lm-studio-local-mode"
variant_b_runtime.app.version = variant_b_runtime.VARIANT_B_VERSION

app = variant_b_runtime.app
