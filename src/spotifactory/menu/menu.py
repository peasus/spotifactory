# menu.py

class MenuItem:
    def __init__(self, label, callback=None, submenu=None):
        self.label = label
        self.callback = callback
        self.submenu = submenu


class Menu:
    def __init__(self, title, items, parent=None, visible_rows=5):
        self.title = title
        self.items = items
        self.selected_index = 0
        self.parent = parent
        self.visible_rows = visible_rows
        self.scroll_offset = 0

    def _update_scroll(self):
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + self.visible_rows:
            self.scroll_offset = self.selected_index - self.visible_rows + 1

    def move_up(self):
        self.selected_index = max(0, self.selected_index - 1)
        self._update_scroll()

    def move_down(self):
        self.selected_index = min(len(self.items) - 1, self.selected_index + 1)
        self._update_scroll()

    def select(self):
        selected = self.items[self.selected_index]

        if selected.submenu:
            selected.submenu.parent = self
            return selected.submenu

        if selected.callback:
            selected.callback()

        return None

    def go_back(self):
        return self.parent
