"""
Persistent storage primitives for enterprise auth and admin state.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from copy import deepcopy
from pathlib import Path

from core.config import DATA_DIR, LOGS_DIR

ENTERPRISE_DIR = DATA_DIR / "enterprise"
ADMIN_STATE_PATH = ENTERPRISE_DIR / "admin_state.json"
SESSION_STATE_PATH = ENTERPRISE_DIR / "session_state.json"
RECOVERY_STATE_PATH = ENTERPRISE_DIR / "recovery_state.json"
ADMIN_EVENTS_PATH = LOGS_DIR / "admin_events.jsonl"

_LOCK = threading.RLock()


def _ensure_dirs() -> None:
    for path in (ADMIN_STATE_PATH, SESSION_STATE_PATH, RECOVERY_STATE_PATH, ADMIN_EVENTS_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, payload: object) -> None:
    tmp_path = path.parent / f"{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def load_admin_state(default_state: dict) -> dict:
    with _LOCK:
        _ensure_dirs()
        if not ADMIN_STATE_PATH.exists():
            _write_json(ADMIN_STATE_PATH, deepcopy(default_state))
        return json.loads(ADMIN_STATE_PATH.read_text(encoding="utf-8"))


def save_admin_state(state: dict) -> None:
    with _LOCK:
        _ensure_dirs()
        _write_json(ADMIN_STATE_PATH, state)


def reset_admin_state_store(default_state: dict) -> dict:
    state = deepcopy(default_state)
    save_admin_state(state)
    return state


def load_session_state() -> dict:
    with _LOCK:
        _ensure_dirs()
        if not SESSION_STATE_PATH.exists():
            _write_json(SESSION_STATE_PATH, {"sessions": {}})
        return json.loads(SESSION_STATE_PATH.read_text(encoding="utf-8"))


def save_session_state(state: dict) -> None:
    with _LOCK:
        _ensure_dirs()
        _write_json(SESSION_STATE_PATH, state)


def update_session_state(mutator) -> dict:
    with _LOCK:
        _ensure_dirs()
        if not SESSION_STATE_PATH.exists():
            _write_json(SESSION_STATE_PATH, {"sessions": {}})
        state = json.loads(SESSION_STATE_PATH.read_text(encoding="utf-8"))
        next_state = mutator(deepcopy(state))
        if next_state is None:
            next_state = state
        _write_json(SESSION_STATE_PATH, next_state)
        return deepcopy(next_state)


def reset_session_state() -> None:
    save_session_state({"sessions": {}})


def load_recovery_state() -> dict:
    with _LOCK:
        _ensure_dirs()
        if not RECOVERY_STATE_PATH.exists():
            _write_json(RECOVERY_STATE_PATH, {"requests": [], "password_reset_tokens": []})
        payload = json.loads(RECOVERY_STATE_PATH.read_text(encoding="utf-8"))
        if "requests" not in payload or not isinstance(payload.get("requests"), list):
            payload["requests"] = []
        if "password_reset_tokens" not in payload or not isinstance(payload.get("password_reset_tokens"), list):
            payload["password_reset_tokens"] = []
        return payload


def save_recovery_state(state: dict) -> None:
    with _LOCK:
        _ensure_dirs()
        _write_json(RECOVERY_STATE_PATH, state)


def reset_recovery_state() -> None:
    save_recovery_state({"requests": [], "password_reset_tokens": []})


def append_admin_event(event: dict) -> None:
    with _LOCK:
        _ensure_dirs()
        with ADMIN_EVENTS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
