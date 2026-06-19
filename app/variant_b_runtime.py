from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, Field

import app.main as runtime
from app.services.ai_provider import AIProviderError, generate_ai_response

VARIANT_B_VERSION = "3.5.4-variant-b-auto-repair"
PIPELINE_ID = "variant_b_backend_turn_v1"

app = runtime.app
app.version = VARIANT_B_VERSION


def _remove_route(path: str, methods: set[str]) -> None:
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and bool(set(getattr(route, "methods", set()) or set()) & methods)
        )
    ]


_remove_route("/", {"GET"})
_remove_route("/health", {"GET"})


@app.get("/")
def variant_b_root() -> dict[str, Any]:
    return {
        "success": True,
        "project": runtime.PROJECT_SLUG,
        "version": VARIANT_B_VERSION,
        "pipeline": PIPELINE_ID,
        "health": "/health",
        "actions_schema": "/openapi-v2-actions.json",
        "turn_endpoint": "/api/v2/sessions/{session_id}/turn",
    }


@app.get("/health")
def variant_b_health() -> dict[str, Any]:
    return {
        "success": True,
        "project": runtime.PROJECT_SLUG,
        "version": VARIANT_B_VERSION,
        "pipeline": PIPELINE_ID,
        "time": runtime.utc_now(),
    }


PLAIN_CHARACTER_LABELS = {
    "akira": "Акира",
    "livia": "Ливия",
    "kir": "Кир",
    "kiara": "Киара",
    "haru": "Хару",
    "raiden": "Райден",
    "samuel": "Самуэль",
    "kael_north": "Каэль",
}

for _cid, _label in PLAIN_CHARACTER_LABELS.items():
    runtime.CHARACTER_FOLDERS.setdefault(_cid, _cid.replace("kael_north", "kael"))
    runtime.CHARACTER_HEADER_LABELS.setdefault(_cid, _label)

runtime.LOCATION_REQUIRED_FILES.setdefault(
    "academy_back_court_exit",
    [
        "world/locations/academy_back_court_exit/location_card.yaml",
        "world/locations/academy_back_court_exit/visual_description.md",
    ],
)


def _ids(value: Any) -> list[str]:
    return runtime.as_id_list(value)


def _normalize_state_for_v3(session_id: str, current_state: dict[str, Any]) -> dict[str, Any]:
    changed = False

    if not isinstance(current_state.get("pov_character_id"), str):
        current_state["pov_character_id"] = "akira"
        changed = True

    alias_pairs = [
        ("active_character_ids", "active_characters"),
        ("nearby_character_ids", "nearby_characters"),
    ]
    for canonical, legacy in alias_pairs:
        merged = runtime.unique(_ids(current_state.get(canonical)) + _ids(current_state.get(legacy)))
        if merged and current_state.get(canonical) != merged:
            current_state[canonical] = merged
            changed = True

    if current_state.get("active_characters") != current_state.get("active_character_ids"):
        current_state["active_characters"] = list(current_state.get("active_character_ids", []))
        changed = True
    if current_state.get("nearby_characters") != current_state.get("nearby_character_ids"):
        current_state["nearby_characters"] = list(current_state.get("nearby_character_ids", []))
        changed = True

    if changed:
        runtime.write_state(session_id, "current_state.json", current_state)
    return current_state


def _selected_character_ids_compat(current_state: dict[str, Any]) -> dict[str, list[str]]:
    pov_id = current_state.get("pov_character_id")
    active = runtime.unique(_ids(current_state.get("active_character_ids")) + _ids(current_state.get("active_characters")))
    nearby = runtime.unique(_ids(current_state.get("nearby_character_ids")) + _ids(current_state.get("nearby_characters")))
    mentioned = _ids(current_state.get("mentioned_character_ids"))
    scheduled = _ids(current_state.get("scheduled_character_ids"))
    delayed = _ids(current_state.get("delayed_character_ids"))

    full = runtime.unique(([pov_id] if isinstance(pov_id, str) else []) + active + nearby)
    reference = runtime.unique(mentioned + scheduled + delayed)
    reference = [cid for cid in reference if cid not in full]
    return {
        "full": full,
        "reference": reference,
        "active": active,
        "nearby": nearby,
        "mentioned": mentioned,
        "scheduled": scheduled,
        "delayed": delayed,
    }


runtime.selected_character_ids = _selected_character_ids_compat  # type: ignore[assignment]


class TurnV2Request(BaseModel):
    user_input: str = ""
    mode: Literal["play", "technical", "audit"] = "play"
    dry_run: bool = True
    save_result: bool = False
    ai_provider: str | None = None
    include_prompt_bundle: bool = True


class TurnV2Response(BaseModel):
    success: bool
    pipeline: str = PIPELINE_ID
    session_id: str
    mode: str
    dry_run: bool
    provider: str
    scene_text: str
    state_changes_applied: bool = False
    changed_files: list[str] = Field(default_factory=list)
    required_files_status: list[dict[str, Any]] = Field(default_factory=list)
    prompt_bundle: dict[str, Any] | None = None
    error: str | None = None


def _file_status(session_id: str, paths: list[str], limit: int = 40) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in paths[:limit]:
        item: dict[str, Any] = {"path": path, "loaded": False, "chars": 0}
        try:
            text = runtime.read_project_or_runtime_file(path, session_id)
            item["loaded"] = True
            item["chars"] = len(text)
        except Exception as exc:
            item["error"] = str(exc)[:180]
        result.append(item)
    return result


def _system_prompt() -> str:
    return """
Ты — backend-controlled AI writer for интерактивной новеллы “Академия Астрейн · 1198”.
Пользователь играет ТОЛЬКО за Акиру. Не пиши прямую речь Акиры, если пользователь её не дал.

ВЕРНИ ТОЛЬКО JSON object без markdown fences:
{"scene_text":"...","state_changes":{...}}

ЖЁСТКИЙ СТИЛЬ-ГЕЙТ:
Пиши как Academy-prequel engine: плотный интерактивный текст, конкретная физика сцены, социальное давление, короткие реплики, скрытое напряжение. Не писать как добрую школьную экскурсию.

ЗАПРЕЩЁННЫЙ ТОН:
- “студенты дружелюбные”, “тёплая улыбка на окружающих”, “надеюсь”, “довольно”, “кажется очень уверенным”, “не знаю, что происходит”, “какая программа на сегодня”;
- generic-варианты вроде “подойти и поговорить”, “игнорировать и идти”, “ответить на взгляды”;
- дружелюбная Акира, робкая Акира, объясняющаяся Акира;
- Хару как пустой флиртующий красавчик;
- Райден как просто “холодный взгляд” без функции давления.

АКИРА:
Акира v2 poisonous: сухая, точная, ядовитая, внешне спокойная.
Её мысли не должны быть “надеюсь”, “интересно”, “кажется дружелюбно”.
Её внутренний тон: контроль тела, оценка цены разговора, раздражение от внимания, холодная практичность.

ЛИВИЯ:
Старая близкая подруга Акиры. Живая, шумная, тёплая, но не глупая. Считывает взгляды, прикрывает и поддевает, но не забирает выбор игрока.

ХАРУ И РАЙДЕН:
Если они в character_slice, оба должны получить видимый beat.
Хару: рыжий у площадки/мяча/кольца, лёгкость, публичность, любопытство к Акире через действие.
Райден: рядом с Хару как тёмноволосый холодный фон; не обязан говорить, но его молчание/не-смотрение должно давить.

ФОРМАТ scene_text:
🏛️ Академия Астрейн · 1198 г., {дата}, {день недели}
🕒 {время} · 📍 {место}
🌦️ Погода: {погода}
⚙️ Активное состояние сцены: учитывать в тексте, действиях и предметах

✦ POV: Акира · {видимое состояние}
🧥 {одежда / форма / НЕ форма}
◈ {предметы рядом и при себе}

━━━━━━━━━━━━━━━━━━━━

6–14 абзацев сцены. Структура: действие/появление → реакция Ливии → реакция площадки/студентов → beat Хару → beat Райдена → конкретное давление/зацепка → стоп на выборе.

━━━━━━━━━━━━━━━━━━━━

✦ Что можно сделать
Варианты ниже не считаются действием, пока игрок не выбрал.
◈ конкретное действие
◈ конкретное действие
◈ конкретное действие

✦ Что Акира могла бы сказать
— “резкая короткая реплика в стиле Акиры”
— “резкая короткая реплика в стиле Акиры”
— “резкая короткая реплика в стиле Акиры”

✦ Мысли Акиры
— сухая мысль/оценка
— сухая мысль/оценка
— сухая мысль/оценка

ПРАВИЛА:
- Не используй “Что вы делаете?”.
- Не раскрывай скрытый лор.
- Не называй фон Акиры активным, если state говорит, что фон не активен.
- Не надевай форму, если uniform_worn=false.
- Не смешивай кириллицу и латиницу в именах.
- Нижние варианты должны быть полезными для следующего хода, не декоративными.
""".strip()


def _build_prompt_bundle(session_id: str, user_input: str, mode: str) -> tuple[dict[str, Any], list[str]]:
    current_state = runtime.read_json_state(session_id, "current_state.json")
    current_state = runtime.apply_user_variant_selection(session_id, current_state, user_input)
    current_state = runtime.normalize_current_akira_variant_state(session_id, current_state)
    current_state = _normalize_state_for_v3(session_id, current_state)

    required_files = runtime.build_required_files(current_state, mode)
    scene_contract = runtime.compact_scene_contract_for_tool(
        runtime.build_scene_contract(session_id, current_state, mode)
    )

    bundle = {
        "pipeline": PIPELINE_ID,
        "system_prompt": _system_prompt(),
        "session_id": session_id,
        "mode": mode,
        "user_input": user_input,
        "scene_contract": scene_contract,
        "required_files": required_files[:40],
        "style_reference_note": (
            "Target style: dry, cinematic, pressure-heavy Academy prose. "
            "Good beat shape: Akira visible action; Livia almost comments; court reacts; Haru notices through ball/movement; "
            "Raiden is a cold nearby pressure; stop on a concrete choice. No friendly-school prose."
        ),
        "style_micro_example": (
            "НЕ копировать, только ритм: Асфальт ещё держал ночную воду. Мяч ударился о сетку слишком громко для случайности. "
            "Ливия хотела сказать что-то едкое, но успела только вдохнуть. У площадки рыжий поймал мяч одной рукой; рядом тёмноволосый не посмотрел прямо, "
            "и от этого внимание стало неприятнее. Акира оценила проход, людей, расстояние до двери — всё, кроме причины, по которой Академия уже пыталась стать проблемой."
        ),
        "forbidden_generic_phrases": [
            "студенты дружелюбные",
            "тёплая улыбка",
            "надеюсь",
            "довольно уверенно",
            "кажется интересным",
            "что вы делаете",
            "подойти к Хару и вступить в разговор",
            "игнорировать Хару и продолжать идти",
            "ответить на взгляды студентов",
            "сосредоточиться на регистрации",
        ],
        "output_json_contract": {
            "scene_text": "visible scene only, exact scene format, no markdown fence",
            "state_changes": {
                "current_state_changes": {},
                "knowledge_changes": {},
                "relationship_changes": {},
                "open_thread_changes": {},
                "shared_incident_changes": {},
                "inventory_changes": {},
                "character_memory_changes": {},
                "event_seed_changes": {},
                "event_queue_changes": {},
                "director_note_changes": {},
                "gossip_changes": {},
                "rating_changes": {},
                "energy_incident_changes": {},
            },
        },
    }
    return bundle, required_files


def _clean_scene_text(scene_text: str) -> str:
    text = scene_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    text = text.replace("Лivi", "Ливи").replace("Лiviей", "Ливией")
    for bad in ["Что вы делаете?", "Что вы делаете"]:
        text = text.replace(bad, "")
    return text.strip()


def _scene_quality_issues(scene_text: str) -> list[str]:
    lower = scene_text.lower()
    issues: list[str] = []
    forbidden = [
        "тёплая улыбка",
        "дружелюб",
        "надеюсь",
        "довольно увер",
        "кажется интерес",
        "какая программа",
        "не знаю, что",
        "акира может:",
        "подойти к хару",
        "игнорировать хару",
        "ответить на взгляды",
        "сосредоточиться на регистрации",
    ]
    for phrase in forbidden:
        if phrase in lower:
            issues.append(f"generic/soft phrase: {phrase}")
    if "✦ что можно сделать" not in lower:
        issues.append("missing exact action-options block")
    if "✦ что акира могла бы сказать" not in lower:
        issues.append("missing exact speech-options block")
    if "✦ мысли акиры" not in lower:
        issues.append("missing exact thoughts block")
    if scene_text.count("━━━━━━━━") < 2:
        issues.append("missing scene separators")
    if "хару" not in lower:
        issues.append("Haru missing")
    if "райден" not in lower:
        issues.append("Raiden missing")
    if len(scene_text) < 1800:
        issues.append("scene too short / underdeveloped")
    return issues[:8]


def _repair_prompt_bundle(prompt_bundle: dict[str, Any], scene_text: str, issues: list[str]) -> dict[str, Any]:
    repaired = deepcopy(prompt_bundle)
    repaired["quality_repair_required"] = True
    repaired["quality_repair_issues"] = issues
    repaired["failed_scene_excerpt"] = scene_text[:2400]
    repaired["system_prompt"] = (
        str(repaired.get("system_prompt", ""))
        + "\n\nПРЕДЫДУЩИЙ ОТВЕТ ПРОВАЛИЛ STYLE-GATE. Перепиши сцену заново, не редактируй по мелочи. "
        + "Убери мягкий/generic тон. Сделай плотнее, суше, ядовитее, с конкретной физикой. "
        + "Акира не думает романтично/дружелюбно о Хару и Райдене. "
        + "Верни только JSON object без markdown fences."
    )
    return repaired


def _apply_ai_state_changes(session_id: str, scene_text: str, changes: dict[str, Any]) -> dict[str, Any]:
    req = runtime.ApplyTurnResultRequest(
        scene_id=str(changes.get("scene_id") or "variant_b_turn"),
        scene_text=scene_text,
        technical=False,
        current_state_changes=changes.get("current_state_changes", {}) if isinstance(changes.get("current_state_changes"), dict) else {},
        knowledge_changes=changes.get("knowledge_changes", {}) if isinstance(changes.get("knowledge_changes"), dict) else {},
        relationship_changes=changes.get("relationship_changes", {}) if isinstance(changes.get("relationship_changes"), dict) else {},
        open_thread_changes=changes.get("open_thread_changes", {}) if isinstance(changes.get("open_thread_changes"), dict) else {},
        shared_incident_changes=changes.get("shared_incident_changes", {}) if isinstance(changes.get("shared_incident_changes"), dict) else {},
        inventory_changes=changes.get("inventory_changes", {}) if isinstance(changes.get("inventory_changes"), dict) else {},
        character_memory_changes=changes.get("character_memory_changes", {}) if isinstance(changes.get("character_memory_changes"), dict) else {},
        event_seed_changes=changes.get("event_seed_changes", {}) if isinstance(changes.get("event_seed_changes"), dict) else {},
        event_queue_changes=changes.get("event_queue_changes", {}) if isinstance(changes.get("event_queue_changes"), dict) else {},
        director_note_changes=changes.get("director_note_changes", {}) if isinstance(changes.get("director_note_changes"), dict) else {},
        gossip_changes=changes.get("gossip_changes", {}) if isinstance(changes.get("gossip_changes"), dict) else {},
        rating_changes=changes.get("rating_changes", {}) if isinstance(changes.get("rating_changes"), dict) else {},
        energy_incident_changes=changes.get("energy_incident_changes", {}) if isinstance(changes.get("energy_incident_changes"), dict) else {},
    )
    return runtime.apply_turn_result(session_id, req)


@app.post("/api/v2/sessions/{session_id}/turn", response_model=TurnV2Response)
def run_turn_v2(session_id: str, req: TurnV2Request) -> TurnV2Response:
    runtime.reject_reserved_session_id(session_id)
    sid, _ = runtime.ensure_session(session_id, reset=False)
    prompt_bundle, required_files = _build_prompt_bundle(sid, req.user_input, req.mode)
    required_status = _file_status(sid, required_files)

    try:
        ai_result = generate_ai_response(req.ai_provider, prompt_bundle)
    except AIProviderError as exc:
        return TurnV2Response(
            success=False,
            pipeline=PIPELINE_ID,
            session_id=sid,
            mode=req.mode,
            dry_run=req.dry_run,
            provider=req.ai_provider or "env/default",
            scene_text="",
            required_files_status=required_status,
            prompt_bundle=prompt_bundle if req.include_prompt_bundle else None,
            error=str(exc),
        )

    scene_text = _clean_scene_text(str(ai_result.get("scene_text", "")))
    changes = ai_result.get("state_changes", {}) if isinstance(ai_result.get("state_changes"), dict) else {}

    issues = _scene_quality_issues(scene_text)
    if issues and str(ai_result.get("provider", req.ai_provider or "")).lower() != "mock":
        repair_bundle = _repair_prompt_bundle(prompt_bundle, scene_text, issues)
        try:
            repaired_result = generate_ai_response(req.ai_provider, repair_bundle)
            repaired_text = _clean_scene_text(str(repaired_result.get("scene_text", "")))
            repaired_issues = _scene_quality_issues(repaired_text)
            if repaired_text and len(repaired_issues) <= len(issues):
                ai_result = repaired_result
                scene_text = repaired_text
                changes = repaired_result.get("state_changes", {}) if isinstance(repaired_result.get("state_changes"), dict) else {}
        except AIProviderError:
            pass

    changed_files: list[str] = []
    applied = False

    if req.save_result and not req.dry_run and scene_text:
        save_result = _apply_ai_state_changes(sid, scene_text, changes)
        applied = bool(save_result.get("success"))
        changed_files = list(save_result.get("updated_files", [])) if isinstance(save_result.get("updated_files"), list) else []

    return TurnV2Response(
        success=True,
        pipeline=PIPELINE_ID,
        session_id=sid,
        mode=req.mode,
        dry_run=req.dry_run,
        provider=str(ai_result.get("provider", req.ai_provider or "mock")),
        scene_text=scene_text,
        state_changes_applied=applied,
        changed_files=changed_files,
        required_files_status=required_status,
        prompt_bundle=prompt_bundle if req.include_prompt_bundle else None,
    )


@app.get("/openapi-v2-actions.json")
def openapi_v2_actions() -> dict[str, Any]:
    server = runtime.PUBLIC_BASE_URL or "https://your-service.up.railway.app"
    return {
        "openapi": "3.1.0",
        "info": {"title": f"{runtime.PROJECT_SLUG} Variant B Actions", "version": VARIANT_B_VERSION},
        "servers": [{"url": server}],
        "paths": {
            "/health": {
                "get": {
                    "operationId": "healthCheck",
                    "summary": "Check API health",
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/api/v1/sessions": {
                "post": {
                    "operationId": "createSession",
                    "summary": "Create a new runtime session",
                    "requestBody": {
                        "required": False,
                        "content": {"application/json": {"schema": runtime.CreateSessionRequest.model_json_schema()}},
                    },
                    "responses": {"200": {"description": "Session created"}},
                }
            },
            "/api/v2/sessions/{session_id}/turn": {
                "post": {
                    "operationId": "runNovelTurnV2",
                    "summary": "Variant B: backend collects context and runs one novel turn",
                    "parameters": [
                        {"name": "session_id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": TurnV2Request.model_json_schema()}},
                    },
                    "responses": {"200": {"description": "Turn result"}},
                }
            },
        },
    }
