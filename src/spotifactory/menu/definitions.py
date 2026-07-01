from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ItemDef:
    label: str
    task: Any = None          # Task subclass to instantiate and run
    submenu: str | None = None  # key in the menus catalog
    action: str | None = None   # "back", "reboot", "shutdown", "confirm", "cancel"


@dataclass
class MenuDef:
    title: str
    items: list[ItemDef] = field(default_factory=list)
    visible_rows: int = 5
