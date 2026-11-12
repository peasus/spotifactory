from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ItemDef:
    label: str
    task: Any = None          # Task subclass to instantiate and run
    submenu: str | None = None  # key in the menus catalog
    action: str | None = None   # "back", "home", "reboot", "shutdown", "confirm", "cancel"
    data: Any = None            # arbitrary payload stored in ctx.data["selected"] on confirm
    backend: str | None = None  # only shown with this music backend ("spotify", ...)

    def shown(self) -> bool:
        if self.backend is None:
            return True
        from spotifactory import backend
        return backend.name() == self.backend


@dataclass
class MenuDef:
    title: str
    items: list[ItemDef] = field(default_factory=list)
    visible_rows: int = 4
    subtitle: str | None = None
