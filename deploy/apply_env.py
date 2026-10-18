"""Merge KEY=VALUE lines from a provisioning file into a .env file.

Each key replaces its line in the .env (including a commented-out example
line, so the setting lands where it's documented), or is appended if the .env
doesn't mention it. Comments and blank lines in the provisioning file are
skipped. Used by setup.sh; standard library only.

    python3 deploy/apply_env.py PROVISION_FILE ENV_FILE
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def read_values(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if value.strip():                 # blank means "not set": leave the .env alone
            values[key.strip()] = value.strip()
    return values


def merge(values: dict[str, str], env_text: str) -> str:
    lines = env_text.splitlines()
    for key, value in values.items():
        pattern = re.compile(rf"^#?\s*{re.escape(key)}\s*=")
        for i, line in enumerate(lines):
            if pattern.match(line):
                lines[i] = f"{key}={value}"
                break
        else:
            lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def main(provision: str, env: str) -> None:
    values = read_values(Path(provision))
    env_path = Path(env)
    env_path.write_text(merge(values, env_path.read_text() if env_path.exists() else ""))
    print(f"  set: {', '.join(values) or '(nothing)'}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
