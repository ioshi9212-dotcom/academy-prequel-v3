from __future__ import annotations

from typing import Any

import app.main as runtime

_original_get_akira_runtime_variant = runtime.get_akira_runtime_variant
_original_runtime_character_file_for = runtime.runtime_character_file_for


def get_akira_runtime_variant_compat(current_state: dict[str, Any]) -> str:
    profile = str(current_state.get("akira_behavior_profile") or "").lower()
    if profile in {"akira_v2_poisonous", "version_2_poisonous", "v2", "poisonous"}:
        return "version_2_poisonous"
    if profile in {"akira_v1_cold", "version_1_cold", "v1", "cold"}:
        return "version_1_cold"
    return _original_get_akira_runtime_variant(current_state)


def runtime_character_file_for_compat(character_id: str, current_state: dict[str, Any]) -> str | None:
    if character_id in {"akira", "char_akira"}:
        variant = get_akira_runtime_variant_compat(current_state)
        if variant == "version_2_poisonous":
            return "runtime/characters/akira_v2.yaml"
        return "runtime/characters/akira_v1.yaml"
    return _original_runtime_character_file_for(character_id, current_state)


runtime.get_akira_runtime_variant = get_akira_runtime_variant_compat  # type: ignore[assignment]
runtime.runtime_character_file_for = runtime_character_file_for_compat  # type: ignore[assignment]
