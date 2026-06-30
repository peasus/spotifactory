from spotifactory import version
from spotifactory.menu.definitions import ItemDef, MenuDef
from spotifactory.menu.navigation import NavStack


def test_version():
    assert isinstance(version, str)


def test_nav_initial_state():
    menu = MenuDef("Main", [ItemDef("A"), ItemDef("B"), ItemDef("C")])
    nav = NavStack(menu)
    assert nav.current.selected_index == 0
    assert nav.current.menu.title == "Main"


def test_nav_move():
    menu = MenuDef("Main", [ItemDef("A"), ItemDef("B"), ItemDef("C")])
    nav = NavStack(menu)
    nav.current.move_down()
    assert nav.current.selected_index == 1
    nav.current.move_up()
    assert nav.current.selected_index == 0


def test_nav_bounds():
    menu = MenuDef("Main", [ItemDef("A"), ItemDef("B"), ItemDef("C")])
    nav = NavStack(menu)
    for _ in range(100):
        nav.current.move_up()
    assert nav.current.selected_index == 0
    for _ in range(100):
        nav.current.move_down()
    assert nav.current.selected_index == 2


def test_nav_push_pop():
    root = MenuDef("Root", [ItemDef("A")])
    sub = MenuDef("Sub", [ItemDef("B")])
    nav = NavStack(root)
    nav.push(sub)
    assert nav.current.menu.title == "Sub"
    assert nav.depth == 2
    nav.pop()
    assert nav.current.menu.title == "Root"
    assert nav.depth == 1


def test_nav_no_pop_at_root():
    root = MenuDef("Root", [ItemDef("A")])
    nav = NavStack(root)
    assert nav.pop() is False
    assert nav.depth == 1


def test_catalog_structure():
    from spotifactory.menu.catalog import MENUS
    assert "main" in MENUS
    assert "settings" in MENUS
    assert any(item.task is not None for item in MENUS["main"].items)
    assert any(item.submenu == "settings" for item in MENUS["main"].items)
