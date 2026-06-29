from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:8000"


def post_json(path: str, payload: dict, timeout: int = 300) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def create_session() -> str:
    result = post_json("/api/v1/sessions", {})
    session_id = result.get("session_id")
    if not session_id:
        raise RuntimeError(f"Backend did not return session_id: {result}")
    return str(session_id)


def send_turn(session_id: str, user_input: str, save_result: bool = False) -> dict:
    return post_json(
        f"/api/v2/sessions/{session_id}/turn",
        {
            "user_input": user_input,
            "mode": "play",
            "dry_run": not save_result,
            "save_result": save_result,
            "ai_provider": "openai_compatible",
            "include_prompt_bundle": False,
        },
    )


def main() -> int:
    try:
        session_id = create_session()
    except urllib.error.URLError:
        print("Backend is not running. First start start_local_backend.bat")
        return 1
    except Exception as exc:
        print(f"Could not create session: {exc}")
        return 1

    print("Academy Prequel local play")
    print(f"Session: {session_id}")
    print("Type your action and press Enter.")
    print("Commands: /exit — quit, /save — next turn will be saved, /dry — dry-run mode")
    print()

    save_result = False
    while True:
        try:
            user_input = input("ход > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return 0

        if not user_input:
            continue
        if user_input.lower() in {"/exit", "exit", "quit", "выход"}:
            print("Bye.")
            return 0
        if user_input.lower() == "/save":
            save_result = True
            print("Save mode: ON. The next turns will write state changes if backend returns them.")
            continue
        if user_input.lower() == "/dry":
            save_result = False
            print("Dry-run mode: ON. Turns will not write state changes.")
            continue

        try:
            result = send_turn(session_id, user_input, save_result=save_result)
        except urllib.error.URLError as exc:
            print(f"\nBackend/LM Studio connection error: {exc}\n")
            continue
        except Exception as exc:
            print(f"\nTurn failed: {exc}\n")
            continue

        if result.get("error"):
            print("\nERROR:")
            print(result["error"])
            print()
            continue

        scene_text = str(result.get("scene_text") or "").strip()
        print("\n" + (scene_text or "[empty scene_text]") + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
