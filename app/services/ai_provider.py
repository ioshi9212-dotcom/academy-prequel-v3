from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class AIProviderError(RuntimeError):
    pass


def _env_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_disabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"0", "false", "no", "off"}


def _looks_like_local_base_url(base_url: str) -> bool:
    lowered = base_url.lower()
    return "127.0.0.1" in lowered or "localhost" in lowered or "lmstudio" in lowered


def _is_local_lm_studio_mode(base_url: str = "") -> bool:
    return _env_enabled("LOCAL_LM_STUDIO_MODE") or _looks_like_local_base_url(base_url)


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


def _mojibake_score(text: str) -> int:
    return text.count("Ð") + text.count("Ñ") + sum(1 for ch in text if "\x80" <= ch <= "\x9f")


def _repair_mojibake_text(text: str) -> str:
    if not text:
        return text
    original_score = _mojibake_score(text)
    if original_score < 3:
        return text
    try:
        repaired = text.encode("latin1").decode("utf-8")
    except UnicodeError:
        return text
    if repaired and _mojibake_score(repaired) < original_score:
        return repaired
    return text


def _repair_mojibake_values(value: Any) -> Any:
    if isinstance(value, str):
        return _repair_mojibake_text(value)
    if isinstance(value, list):
        return [_repair_mojibake_values(item) for item in value]
    if isinstance(value, dict):
        return {key: _repair_mojibake_values(item) for key, item in value.items()}
    return value


def _json_object_candidates(text: str) -> list[str]:
    cleaned = _strip_markdown_fence(_repair_mojibake_text(text))
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
            parsed_raw = _repair_mojibake_values(parsed_raw)
            scene_text = parsed_raw.get("scene_text")
            if isinstance(scene_text, str):
                nested = _strip_markdown_fence(scene_text)
                if nested != scene_text and nested.strip().startswith("{"):
                    nested_parsed = _parse_model_content(nested)
                    if isinstance(nested_parsed.get("scene_text"), str):
                        return nested_parsed
                parsed_raw["scene_text"] = nested.strip()
            return parsed_raw
    return {"scene_text": _strip_markdown_fence(_repair_mojibake_text(content))}


def _openai_compatible_response(prompt_bundle: dict[str, Any]) -> dict[str, Any]:
    base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL", "").rstrip("/")
    api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY", "")
    model = os.getenv("OPENAI_COMPATIBLE_MODEL", "")
    local_mode = _is_local_lm_studio_mode(base_url)

    default_timeout = "240" if local_mode else "60"
    try:
        timeout = float(os.getenv("OPENAI_COMPATIBLE_TIMEOUT", default_timeout))
    except ValueError as exc:
        raise AIProviderError("OPENAI_COMPATIBLE_TIMEOUT must be a number") from exc

    if not base_url or not model:
        raise AIProviderError("OPENAI_COMPATIBLE_BASE_URL and OPENAI_COMPATIBLE_MODEL are required")
    if not api_key:
        raise AIProviderError("OPENAI_COMPATIBLE_API_KEY is required")

    system = prompt_bundle.get("system_prompt", "")
    user_payload = json.dumps(prompt_bundle, ensure_ascii=False, separators=(",", ":"))
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": str(system)},
            {"role": "user", "content": user_payload},
        ],
        "temperature": float(os.getenv("AI_TEMPERATURE", "0.75")),
    }

    # Groq/OpenAI-compatible providers often support JSON mode. LM Studio rejects
    # json_object for some models, so local mode defaults to plain text unless the
    # user explicitly enables OPENAI_COMPATIBLE_JSON_MODE=true.
    json_mode_default = "false" if local_mode else "true"
    if not _env_disabled("OPENAI_COMPATIBLE_JSON_MODE", default=json_mode_default.lower() in {"0", "false", "no", "off"}):
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
        "AcademyPrequelV3-Railway/3.5.2 (+https://prequel-v3-production.up.railway.app)",
    )
    request_data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=request_data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": user_agent,
            "Authorization": f"Bearer {api_key}",
        },
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
    scene_text = str(parsed.get("scene_text") or "").strip()

    return {
        "provider": "openai_compatible",
        "model": model,
        "scene_text": scene_text,
        "state_changes": parsed.get("state_changes", {}) if isinstance(parsed.get("state_changes"), dict) else {},
        "raw": parsed,
    }


def generate_ai_response(provider: str | None, prompt_bundle: dict[str, Any]) -> dict[str, Any]:
    selected = (provider or os.getenv("AI_PROVIDER") or "mock").strip().lower()
    if selected in {"mock", "dry", "test"}:
        return _mock_response(prompt_bundle)
    if selected in {"openai_compatible", "openai-compatible", "lmstudio", "local"}:
        return _openai_compatible_response(prompt_bundle)
    raise AIProviderError(f"Unsupported AI_PROVIDER: {selected}")
