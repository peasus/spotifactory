from spotifactory import version
from spotifactory.menu.menu import Menu, MenuItem
from spotifactory.menu.menus import build_menu


def test_version():
    assert isinstance(version, str)


def test_menu_navigation():
    menu = build_menu()
    assert menu.selected_index == 0
    menu.move_down()
    assert menu.selected_index == 1
    menu.move_up()
    assert menu.selected_index == 0


def test_menu_select_submenu():
    menu = build_menu()
    # "Settings" is at index 1
    menu.move_down()
    result = menu.select()
    assert result is not None
    assert result.title == "Settings"
    assert result.parent is menu


def test_menu_go_back():
    menu = build_menu()
    menu.move_down()
    submenu = menu.select()
    assert submenu.go_back() is menu


def test_menu_bounds():
    menu = build_menu()
    for _ in range(100):
        menu.move_up()
    assert menu.selected_index == 0
    for _ in range(100):
        menu.move_down()
    assert menu.selected_index == len(menu.items) - 1
