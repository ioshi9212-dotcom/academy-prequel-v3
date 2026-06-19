from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.getenv("DATA_DIR", "/data"))
PROJECT_ROOT = DATA_ROOT / "project"
SESSIONS_ROOT = DATA_ROOT / "sessions"
SESSION_RE = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")

SYNC_DIRS = [
    "canon",
    "characters",
    "engine",
    "gpt",
    "knowledge",
    "relationships",
    "runtime",
    "state",
    "story",
    "templates",
    "validation",
    "world",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_repo_path(path: str) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path is empty")
    normalized = path.replace("\\", "/").strip().lstrip("/")
    parts = [part for part in normalized.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise ValueError("path traversal is not allowed")
    return "/".join(parts)


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        if not path.exists():
            return default
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return default
        return json.loads(text)
    except Exception:
        return default


def _copy_dir(src: Path, dst: Path) -> None:
    if not src.exists() or not src.is_dir():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))


def ensure_runtime_root() -> Path:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    PROJECT_ROOT.mkdir(parents=True, exist_ok=True)
    SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)

    for dirname in SYNC_DIRS:
        src = REPO_ROOT / dirname
        dst = PROJECT_ROOT / dirname
        if src.exists() and src.is_dir():
            # Keep repository seed mirrored in /data so Railway volume has a stable project copy.
            _copy_dir(src, dst)
    return DATA_ROOT


def _new_session_id() -> str:
    return "session_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8]


def session_root(session_id: str) -> Path:
    safe = safe_session_id(session_id)
    return SESSIONS_ROOT / safe


def session_state_root(session_id: str) -> Path:
    return session_root(session_id) / "state"


def safe_session_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not SESSION_RE.match(session_id):
        raise ValueError("invalid session_id")
    return session_id


def ensure_session(session_id: str | None = None, reset: bool = False) -> tuple[str, Path]:
    ensure_runtime_root()
    sid = safe_session_id(session_id) if session_id else _new_session_id()
    root = session_root(sid)
    state_root = session_state_root(sid)

    root.mkdir(parents=True, exist_ok=True)
    state_root.mkdir(parents=True, exist_ok=True)

    seed_state = PROJECT_ROOT / "state"
    if reset or not any(state_root.iterdir()):
        if seed_state.exists():
            for item in seed_state.iterdir():
                dst = state_root / item.name
                if item.is_dir():
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(item, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dst)
        (state_root / "character_memory").mkdir(parents=True, exist_ok=True)
        session_meta = {
            "session_id": sid,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "runtime": "academy_prequel_v3_variant_b",
        }
        write_json_atomic(root / "session.json", session_meta)

    return sid, root


def read_state(session_id: str, filename: str) -> Any:
    safe_name = safe_repo_path(filename)
    path = session_state_root(session_id) / safe_name
    if path.suffix.lower() == ".json":
        return read_json(path, {})
    if path.exists():
        return path.read_text(encoding="utf-8")
    return {} if path.suffix.lower() == ".json" else ""


def write_state(session_id: str, filename: str, content: Any) -> None:
    safe_name = safe_repo_path(filename)
    path = session_state_root(session_id) / safe_name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (dict, list)) or path.suffix.lower() == ".json":
        write_json_atomic(path, content)
    else:
        path.write_text(str(content), encoding="utf-8")


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def read_project_or_runtime_file(path: str, session_id: str | None = None) -> str:
    safe = safe_repo_path(path)

    candidates: list[Path] = []
    if session_id:
        try:
            safe_session_id(session_id)
            if safe.startswith("state/"):
                candidates.append(session_state_root(session_id) / safe[len("state/"):])
            candidates.append(session_root(session_id) / safe)
        except Exception:
            pass

    candidates.extend([
        PROJECT_ROOT / safe,
        REPO_ROOT / safe,
        DATA_ROOT / safe,
    ])

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise FileNotFoundError(safe)


def debug_info() -> dict[str, Any]:
    ensure_runtime_root()
    return {
        "data_root": str(DATA_ROOT),
        "project_root": str(PROJECT_ROOT),
        "sessions_root": str(SESSIONS_ROOT),
        "project_root_exists": PROJECT_ROOT.exists(),
        "sessions_root_exists": SESSIONS_ROOT.exists(),
        "synced_dirs": [name for name in SYNC_DIRS if (PROJECT_ROOT / name).exists()],
        "repo_root": str(REPO_ROOT),
    }
