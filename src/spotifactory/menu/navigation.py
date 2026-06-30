from dataclasses import dataclass

from spotifactory.menu.definitions import MenuDef, ItemDef


@dataclass
class NavState:
    menu: MenuDef
    selected_index: int = 0
    scroll_offset: int = 0

    def move_up(self) -> None:
        if self.selected_index > 0:
            self.selected_index -= 1
            self._clamp_scroll()

    def move_down(self) -> None:
        if self.selected_index < len(self.menu.items) - 1:
            self.selected_index += 1
            self._clamp_scroll()

    def _clamp_scroll(self) -> None:
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + self.menu.visible_rows:
            self.scroll_offset = self.selected_index - self.menu.visible_rows + 1

    @property
    def selected_item(self) -> ItemDef:
        return self.menu.items[self.selected_index]

    @property
    def visible_items(self) -> list[tuple[int, ItemDef]]:
        start = self.scroll_offset
        return [
            (start + i, item)
            for i, item in enumerate(self.menu.items[start : start + self.menu.visible_rows])
        ]


class NavStack:
    def __init__(self, root: MenuDef) -> None:
        self._stack: list[NavState] = [NavState(root)]

    @property
    def current(self) -> NavState:
        return self._stack[-1]

    def push(self, menu: MenuDef) -> None:
        self._stack.append(NavState(menu))

    def pop(self) -> bool:
        if len(self._stack) > 1:
            self._stack.pop()
            return True
        return False

    @property
    def depth(self) -> int:
        return len(self._stack)
