from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
import subprocess
from pathlib import Path
from typing import Any, Optional


LOG_DIR = Path("logs")
LOG_PATH = LOG_DIR / "codex_interactions.jsonl"
SESSION_PATH = LOG_DIR / "current_session.json"
def _detect_codex_version() -> str:
    env_ver = os.environ.get("CODEX_VERSION")
    if env_ver:
        return env_ver
    try:
        proc = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=2)
        out = (proc.stdout or proc.stderr or "").strip()
        if out:
            return out
    except Exception:
        pass
    return "CLI"


CODEX_VERSION = _detect_codex_version()


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_dirs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _write_jsonl(path: Path, obj: dict) -> None:
    _ensure_dirs()
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _read_session() -> Optional[dict]:
    try:
        if SESSION_PATH.exists():
            with open(SESSION_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _write_session(rec: dict) -> None:
    _ensure_dirs()
    with open(SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)


def get_session(create_if_missing: bool = True) -> dict:
    rec = _read_session()
    if rec:
        return rec
    if not create_if_missing:
        return {}
    session_id = os.environ.get("CODEX_SESSION_ID") or str(uuid.uuid4())
    rec = {"id": session_id, "started": _utcnow_z()}
    _write_session(rec)
    # Write a session_start record
    _write_jsonl(LOG_PATH, {"ts": _utcnow_z(), "type": "session_start", "session": rec})
    return rec


def start_new_session(note: Optional[str] = None) -> dict:
    session_id = os.environ.get("CODEX_SESSION_ID") or str(uuid.uuid4())
    rec = {"id": session_id, "started": _utcnow_z(), "note": note}
    _write_session(rec)
    _write_jsonl(LOG_PATH, {"ts": _utcnow_z(), "type": "session_start", "session": rec})
    return rec


def append_interaction(role: str, message: str, **meta: Any) -> None:
    session = get_session(create_if_missing=True)
    role_label = role
    if isinstance(role, str) and role.lower() in {"assistant", "codex"}:
        role_label = CODEX_VERSION or "codex-cli"
    entry = {
        "ts": _utcnow_z(),
        "type": "interaction",
        "session_id": session.get("id"),
        "role": role_label,
        "message": message,
    }
    if meta:
        entry.update({"meta": meta})
    _write_jsonl(LOG_PATH, entry)


def append_tool_event(name: str, **meta: Any) -> None:
    session = get_session(create_if_missing=True)
    entry = {
        "ts": _utcnow_z(),
        "type": "tool",
        "session_id": session.get("id"),
        "name": name,
        "meta": meta,
    }
    _write_jsonl(LOG_PATH, entry)


def end_session(reason: Optional[str] = None) -> None:
    session = get_session(create_if_missing=False)
    if not session:
        return
    _write_jsonl(LOG_PATH, {"ts": _utcnow_z(), "type": "session_end", "session_id": session.get("id"), "reason": reason})
    try:
        SESSION_PATH.unlink(missing_ok=True)  # type: ignore[arg-type]
    except Exception:
        pass


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: python codex_logger.py [start|log|tool|end] [args...]")
        return 2
    cmd = argv[1].lower()
    if cmd == "start":
        note = " ".join(argv[2:]) if len(argv) > 2 else None
        rec = start_new_session(note=note)
        print(f"Started session {rec['id']}")
        return 0
    if cmd == "log":
        role = argv[2] if len(argv) > 2 else "assistant"
        msg = " ".join(argv[3:]) if len(argv) > 3 else ""
        append_interaction(role, msg)
        return 0
    if cmd == "tool":
        name = argv[2] if len(argv) > 2 else "unknown"
        append_tool_event(name)
        return 0
    if cmd == "end":
        reason = " ".join(argv[2:]) if len(argv) > 2 else None
        end_session(reason)
        return 0
    print(f"Unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
