# Academy Prequel V3 / Variant B runtime entrypoint.
# Railway runs `uvicorn app.server:app`; keep this file as the stable shim.

from __future__ import annotations

import os
from typing import Any

import app.variant_b_runtime as variant_b_runtime


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _local_lmstudio_context_mode() -> bool:
    if _env_flag("LOCAL_LM_STUDIO_MODE", False):
        return True
    selected_provider = os.getenv("AI_PROVIDER", "").strip().lower()
    if selected_provider in {"lmstudio", "lm-studio", "local", "local_lm_studio"}:
        return True
    base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL", "").lower()
    return any(marker in base_url for marker in ("127.0.0.1", "localhost", "0.0.0.0"))


def _prioritized_source_paths(paths: list[str]) -> list[str]:
    high_signal = [
        "engine/live_scene_depth_rules.md",
        "runtime/characters/akira.yaml",
        "runtime/characters/livia.yaml",
        "runtime/characters/haru.yaml",
        "runtime/characters/raiden.yaml",
        "relationships/relationships_index.yaml",
        "story/calendar/academy_start.yaml",
        "story/arcs/arc_001_academy_start.yaml",
        "world/locations/academy_back_court_exit/location_card.yaml",
        "world/locations/academy_back_court_exit/visual_description.md",
        "engine/output_format.md",
        "engine/pov_rules.md",
        "engine/prose_style_rules.md",
        "engine/scene_generation_rules.md",
        "gpt/locks/character_presence_rotation_lock.md",
        "gpt/locks/npc_living_scene_rules.md",
    ]
    merged: list[str] = []
    for path in high_signal + list(paths):
        if isinstance(path, str) and path and path not in merged:
            merged.append(path)
    return merged


def _path_file_limit(path: str, default_limit: int, local_mode: bool) -> int:
    if path == "engine/live_scene_depth_rules.md":
        return min(default_limit + (700 if local_mode else 1200), 2200)
    if path.startswith("runtime/characters/"):
        return min(default_limit + (250 if local_mode else 600), 1800)
    if path.startswith("relationships/"):
        return min(default_limit + 250, 1500)
    if path.startswith("story/calendar/") or path.startswith("story/arcs/"):
        return min(default_limit + 150, 1400)
    if path.startswith("world/locations/"):
        return min(default_limit + 150, 1300)
    return default_limit


def _compact_load_source_context(
    session_id: str,
    paths: list[str],
    max_total_chars: int | None = None,
    max_file_chars: int | None = None,
) -> list[dict[str, Any]]:
    """Keep the source pack compact, but do not strip away character depth."""
    runtime = variant_b_runtime.runtime
    local_mode = _local_lmstudio_context_mode()
    total_default = "3400" if local_mode else "9000"
    file_default = "520" if local_mode else "1000"
    total_limit = max_total_chars or int(os.getenv("SOURCE_CONTEXT_MAX_CHARS", total_default))
    file_limit = max_file_chars or int(os.getenv("SOURCE_CONTEXT_FILE_MAX_CHARS", file_default))

    result: list[dict[str, Any]] = []
    total = 0
    for path in _prioritized_source_paths(paths):
        if total >= total_limit:
            break
        try:
            text = runtime.read_project_or_runtime_file(path, session_id)
        except Exception:
            continue
        per_file_limit = _path_file_limit(path, file_limit, local_mode)
        trimmed = text[:per_file_limit]
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
        "source_context_priority": "Use engine/live_scene_depth_rules.md first, then active character runtime summaries, then relationships/location/calendar.",
        "pov_filter": "Describe people only through what Akira can observe and judge. No objective labels like charismatic/confident/interesting.",
        "dialogue_format": "Descriptions/remarks in italics. Character speech as **Name** — text. Do not write Akira speech unless user wrote it.",
        "action_weight_rule": "Each action option must include a distinct consequence weight: risk, information, social pressure, speed, relationship, or control.",
        "thought_rule": "Akira thoughts must be concrete working assessments, not philosophy or friendly curiosity.",
        "npc_living_rule": "NPC and named characters have their own goal/knowledge/reaction. Akira's intent is not a command for the world.",
    }
    bundle["scene_depth_contract"] = {
        "rule": "A scene must show at least one concrete consequence/reaction from a present or nearby character when the player action creates pressure.",
        "no_functional_npcs": True,
        "visible_reaction_only": "NPCs react to words, tone, movement, distance, public context, injury, energy or what they already know — not to hidden author truth.",
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
                "уверенный парень",
                "интересный Райден",
                "Райден кажется интересным",
                "Вопрос был, как Акира решила бы",
                "все замолчали",
                "все посмотрели на Акиру",
                "Академия казалась дружелюбной",
            ]
        )
    )
    return bundle, required_files


def _repair_toggle_quality_issues(scene_text: str) -> list[str]:
    """Allow disabling the second model call when free TPM/local latency is tight."""
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
    if "все замолчали" in lower or "все посмотрели" in lower:
        issues.append("crowd reacts as one synchronized mass")
    return issues[:12]


variant_b_runtime._load_source_context = _compact_load_source_context

if not hasattr(variant_b_runtime, "_original_build_prompt_bundle"):
    variant_b_runtime._original_build_prompt_bundle = variant_b_runtime._build_prompt_bundle
variant_b_runtime._build_prompt_bundle = _safe_build_prompt_bundle

if not hasattr(variant_b_runtime, "_original_scene_quality_issues"):
    variant_b_runtime._original_scene_quality_issues = variant_b_runtime._scene_quality_issues
variant_b_runtime._scene_quality_issues = _repair_toggle_quality_issues

variant_b_runtime.VARIANT_B_VERSION = "3.5.10-local-lmstudio-scene-depth"
variant_b_runtime.app.version = variant_b_runtime.VARIANT_B_VERSION

app = variant_b_runtime.app
