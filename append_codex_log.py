from __future__ import annotations

import sys
from datetime import datetime, timezone
import os
import subprocess
from pathlib import Path


# Allow a global override. If CODEX_LOG_PATH is set, use it; otherwise write
# to a local ./codex_log.txt in the current working directory.
LOG_TXT = Path(os.environ.get("CODEX_LOG_PATH", "codex_log.txt")).expanduser()


def _detect_codex_version() -> str:
    # Priority: explicit env var
    env_ver = os.environ.get("CODEX_VERSION")
    if env_ver:
        return env_ver
    # Try calling codex --version if available
    try:
        proc = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=2)
        out = (proc.stdout or proc.stderr or "").strip()
        if out:
            return out
    except Exception:
        pass
    return "CLI"


CODEX_VERSION = _detect_codex_version()


def now_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def append(role: str, message: str) -> None:
    ts = now_z()
    role_label = role
    if role.lower() in {"assistant", "codex"}:
        role_label = CODEX_VERSION or "codex-cli"
    header = f"[{ts}] role={role_label}"
    sep = "-" * 60
    with open(LOG_TXT, "a", encoding="utf-8") as f:
        f.write(header + "\n")
        f.write(message.rstrip("\n") + "\n")
        f.write(sep + "\n")


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("Usage: python append_codex_log.py <role> <message or ->")
        return 2
    role = argv[1]
    if argv[2] == "-":
        msg = sys.stdin.read()
    else:
        msg = " ".join(argv[2:])
    append(role, msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
