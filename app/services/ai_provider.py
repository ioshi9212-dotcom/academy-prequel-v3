from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


class AIProviderError(RuntimeError):
    pass


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _is_local_compatible_endpoint(base_url: str, provider: str | None = None) -> bool:
    selected = (provider or "").strip().lower()
    if selected in {"lmstudio", "lm-studio", "local", "local_lm_studio"}:
        return True
    if _env_flag("LOCAL_LM_STUDIO_MODE", False):
        return True
    lowered = base_url.lower()
    return any(marker in lowered for marker in ("127.0.0.1", "localhost", "0.0.0.0"))


def _mock_response(prompt_bundle: dict[str, Any]) -> dict[str, Any]:
    user_input = str(prompt_bundle.get("user_input", "")).strip()
    contract = prompt_bundle.get("scene_contract", {}) if isinstance(prompt_bundle.get("scene_contract"), dict) else {}
    frame = contract.get("current_frame", {}) if isinstance(contract.get("current_frame"), dict) else {}
    header_values = frame.get("header_values", {}) if isinstance(frame.get("header_values"), dict) else {}

    scene_text = "\n".join(
        [
            "[MOCK AI / Variant B]",
            "Пакет хода собран backend-движком. Реальная модель ещё не подключена.",
            f"Дата: {header_values.get('date_human') or frame.get('date') or 'не указана'}",
            f"Место: {header_values.get('location_human') or frame.get('location_id') or 'не указано'}",
            f"Ход игрока: {user_input or 'пустой ход'}",
        ]
    )
    return {
        "provider": "mock",
        "model": "mock-v0",
        "scene_text": scene_text,
        "state_changes": {},
        "raw": {"note": "Mock provider does not write canon."},
    }


def _http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")[:1500]
    except Exception:
        return ""


def _strip_markdown_fence(text: str) -> str:
    value = text.strip()
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _strip_model_thinking(text: str) -> str:
    value = text.strip()
    value = re.sub(r"<think>.*?</think>", "", value, flags=re.DOTALL | re.IGNORECASE).strip()
    value = re.sub(r"<analysis>.*?</analysis>", "", value, flags=re.DOTALL | re.IGNORECASE).strip()
    return value


def _cyrillic_score(text: str) -> int:
    return sum(1 for char in text if "А" <= char <= "я" or char == "ё" or char == "Ё")


def _repair_common_mojibake(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text
    markers = ("Ð", "Ñ", "Рђ", "Р°", "Рµ", "Рё", "СЃ", "С‚")
    if not any(marker in text for marker in markers):
        return text

    best = text
    best_score = _cyrillic_score(text)
    for encoding in ("latin1", "cp1252"):
        try:
            repaired = text.encode(encoding, errors="ignore").decode("utf-8", errors="ignore")
        except Exception:
            continue
        score = _cyrillic_score(repaired)
        if score > best_score:
            best = repaired
            best_score = score
    return best


def _json_object_candidates(text: str) -> list[str]:
    cleaned = _strip_markdown_fence(_strip_model_thinking(_repair_common_mojibake(text)))
    candidates = [cleaned]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        extracted = cleaned[start : end + 1].strip()
        if extracted not in candidates:
            candidates.append(extracted)
    return candidates


def _parse_model_content(content: str) -> dict[str, Any]:
    for candidate in _json_object_candidates(content):
        try:
            parsed_raw = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed_raw, dict):
            scene_text = parsed_raw.get("scene_text")
            if isinstance(scene_text, str):
                nested = _strip_markdown_fence(_strip_model_thinking(_repair_common_mojibake(scene_text)))
                if nested != scene_text and nested.strip().startswith("{"):
                    nested_parsed = _parse_model_content(nested)
                    if isinstance(nested_parsed.get("scene_text"), str):
                        return nested_parsed
                parsed_raw["scene_text"] = nested.strip()
            return parsed_raw
    return {"scene_text": _strip_markdown_fence(_strip_model_thinking(_repair_common_mojibake(content)))}


def _openai_compatible_response(prompt_bundle: dict[str, Any], provider: str | None = None) -> dict[str, Any]:
    base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL", "").rstrip("/")
    model = os.getenv("OPENAI_COMPATIBLE_MODEL", "")
    local_mode = _is_local_compatible_endpoint(base_url, provider)
    api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY", "") or ("lm-studio" if local_mode else "")

    try:
        timeout_default = "240" if local_mode else "60"
        timeout = float(os.getenv("OPENAI_COMPATIBLE_TIMEOUT", timeout_default))
    except ValueError as exc:
        raise AIProviderError("OPENAI_COMPATIBLE_TIMEOUT must be a number") from exc

    if not base_url or not model:
        raise AIProviderError("OPENAI_COMPATIBLE_BASE_URL and OPENAI_COMPATIBLE_MODEL are required")
    if not api_key:
        raise AIProviderError("OPENAI_COMPATIBLE_API_KEY is required")

    system = prompt_bundle.get("system_prompt", "")
    user_payload = json.dumps(prompt_bundle, ensure_ascii=False)
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": str(system)},
            {"role": "user", "content": user_payload},
        ],
        "temperature": float(os.getenv("AI_TEMPERATURE", "0.75")),
    }

    # Groq/OpenAI-compatible providers often support JSON mode, but LM Studio's
    # OpenAI-compatible server rejects response_format={"type":"json_object"} for
    # some local models. Default JSON mode off for local mode, on for remote mode.
    json_mode_env = os.getenv("OPENAI_COMPATIBLE_JSON_MODE")
    json_mode_enabled = _env_flag("OPENAI_COMPATIBLE_JSON_MODE", default=not local_mode)
    if json_mode_env is not None and json_mode_enabled:
        body["response_format"] = {"type": "json_object"}
    elif json_mode_env is None and json_mode_enabled:
        body["response_format"] = {"type": "json_object"}

    max_tokens = os.getenv("AI_MAX_TOKENS") or os.getenv("OPENAI_COMPATIBLE_MAX_TOKENS")
    if not max_tokens and local_mode:
        max_tokens = "600"
    if max_tokens:
        try:
            body["max_tokens"] = int(max_tokens)
        except ValueError as exc:
            raise AIProviderError("AI_MAX_TOKENS / OPENAI_COMPATIBLE_MAX_TOKENS must be an integer") from exc

    url = f"{base_url}/chat/completions"
    user_agent = os.getenv(
        "OPENAI_COMPATIBLE_USER_AGENT",
        "AcademyPrequelV3/3.5.10 (+local-lm-studio-compatible)",
    )
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "User-Agent": user_agent,
        "Authorization": f"Bearer {api_key}",
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-configured endpoint
            raw_response = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body_text = _http_error_body(exc)
        raise AIProviderError(f"OpenAI-compatible HTTP {exc.code}: {body_text or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise AIProviderError(f"OpenAI-compatible connection error: {exc.reason}") from exc
    except TimeoutError as exc:
        raise AIProviderError("OpenAI-compatible request timed out") from exc
    except Exception as exc:
        raise AIProviderError(f"OpenAI-compatible request failed: {type(exc).__name__}: {exc}") from exc

    try:
        payload = json.loads(raw_response)
    except Exception as exc:
        raise AIProviderError(f"Invalid JSON from OpenAI-compatible provider: {raw_response[:800]}") from exc

    try:
        content = payload["choices"][0]["message"]["content"]
    except Exception as exc:
        raise AIProviderError(f"Invalid OpenAI-compatible response shape: {exc}; payload={str(payload)[:1000]}") from exc

    parsed = _parse_model_content(str(content))
    scene_text = _repair_common_mojibake(str(parsed.get("scene_text") or "")).strip()

    return {
        "provider": "lmstudio" if local_mode else "openai_compatible",
        "model": model,
        "scene_text": scene_text,
        "state_changes": parsed.get("state_changes", {}) if isinstance(parsed.get("state_changes"), dict) else {},
        "raw": parsed,
    }


def generate_ai_response(provider: str | None, prompt_bundle: dict[str, Any]) -> dict[str, Any]:
    selected = (provider or os.getenv("AI_PROVIDER") or "mock").strip().lower()
    if selected in {"mock", "dry", "test"}:
        return _mock_response(prompt_bundle)
    if selected in {"openai_compatible", "openai-compatible", "lmstudio", "lm-studio", "local", "local_lm_studio"}:
        return _openai_compatible_response(prompt_bundle, selected)
    raise AIProviderError(f"Unsupported AI_PROVIDER: {selected}")
