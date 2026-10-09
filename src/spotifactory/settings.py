"""Device settings chosen on the device itself (speaker, printer, BT MACs).

Stored in the project's .env next to the credentials, so they're loaded at
startup by load_dotenv() like everything else.
"""
from __future__ import annotations

import os
import pathlib


def env_path() -> str:
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return str(parent / ".env")
    return ".env"


def save_setting(key: str, value: str) -> None:
    """Apply to the running process now and persist to .env for the next start."""
    os.environ[key] = value
    try:
        from dotenv import set_key
        set_key(env_path(), key, value)
    except Exception as e:
        print(f"[settings] couldn't save {key}: {e}", flush=True)
