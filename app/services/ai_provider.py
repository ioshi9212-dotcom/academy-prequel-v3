from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class AIProviderError(RuntimeError):
    pass


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
        "raw": {
            "note": "Mock provider does not write canon. Use dry_run to inspect the assembled prompt bundle.",
        },
    }


def _http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")[:1500]
    except Exception:
        return ""


def _openai_compatible_response(prompt_bundle: dict[str, Any]) -> dict[str, Any]:
    base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL", "").rstrip("/")
    api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY", "")
    model = os.getenv("OPENAI_COMPATIBLE_MODEL", "")

    try:
        timeout = float(os.getenv("OPENAI_COMPATIBLE_TIMEOUT", "60"))
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

    max_tokens = os.getenv("AI_MAX_TOKENS") or os.getenv("OPENAI_COMPATIBLE_MAX_TOKENS")
    if max_tokens:
        try:
            body["max_tokens"] = int(max_tokens)
        except ValueError as exc:
            raise AIProviderError("AI_MAX_TOKENS / OPENAI_COMPATIBLE_MAX_TOKENS must be an integer") from exc

    url = f"{base_url}/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-configured endpoint
            raw_response = response.read().decode("utf-8")
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

    content = ""
    try:
        content = payload["choices"][0]["message"]["content"]
    except Exception as exc:
        raise AIProviderError(f"Invalid OpenAI-compatible response shape: {exc}; payload={str(payload)[:1000]}") from exc

    parsed: dict[str, Any]
    try:
        parsed_raw = json.loads(content)
        parsed = parsed_raw if isinstance(parsed_raw, dict) else {"scene_text": str(content)}
    except Exception:
        parsed = {"scene_text": content}

    return {
        "provider": "openai_compatible",
        "model": model,
        "scene_text": str(parsed.get("scene_text", content)),
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
