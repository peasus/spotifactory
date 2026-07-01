import time

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
    assert any(item.task is not None for item in MENUS["main"].items)
    assert any(item.action == "home" for item in MENUS["main"].items)


# ---------------------------------------------------------------------------
# Step dry-run tests — verify no real hardware is touched in sim mode
# ---------------------------------------------------------------------------

def _wait_for_done(step, timeout=2.0):
    """Poll step.is_done up to timeout seconds; return True if done."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if step.is_done:
            return True
        time.sleep(0.05)
    return False


def test_play_tag_scan_step_dry_run():
    """ScanStep does not touch RFID hardware in dry_run mode."""
    from spotifactory.tasks.base import Continue, TaskContext
    from spotifactory.tasks.play_tag.steps import ScanStep

    ctx = TaskContext(dry_run=True, data={})
    step = ScanStep()
    step.start(ctx)
    assert _wait_for_done(step), "ScanStep timed out in dry_run mode"
    assert isinstance(step.outcome, Continue), f"unexpected outcome: {step.outcome}"
    assert "uri" in ctx.data, "ScanStep should populate ctx.data['uri'] in dry_run"


def test_home_scan_step_simulate_scan():
    """HomeScanStep advances with Continue when simulate_scan() is called.

    HomeScanStep always tries real hardware first; in CI/Mac without a reader
    it falls back to a soft-wait loop.  simulate_scan() unblocks either path.
    """
    from spotifactory.tasks.base import Continue, TaskContext
    from spotifactory.tasks.home.steps import HomeScanStep

    sim_uri = "spotify:album:test_simulate"
    ctx = TaskContext(dry_run=False, data={})
    step = HomeScanStep()
    step.start(ctx)

    time.sleep(0.2)  # let the step reach the wait loop (after hardware attempt)
    assert not step.is_done

    step.simulate_scan(sim_uri)
    assert _wait_for_done(step, timeout=3.0), "HomeScanStep timed out after simulate_scan"
    assert isinstance(step.outcome, Continue)
    assert ctx.data.get("uri") == sim_uri


def test_home_scan_step_cancel():
    """HomeScanStep returns Cancel when cancel() is called."""
    from spotifactory.tasks.base import Cancel, TaskContext
    from spotifactory.tasks.home.steps import HomeScanStep

    ctx = TaskContext(dry_run=False, data={})
    step = HomeScanStep()
    step.start(ctx)

    time.sleep(0.2)
    assert not step.is_done

    step.cancel()
    assert _wait_for_done(step, timeout=3.0), "HomeScanStep timed out after cancel"
    assert isinstance(step.outcome, Cancel)


def test_step_execute_exception_surfaces_as_done():
    """If Step.run() raises, _execute sets a Done() outcome instead of hanging."""
    from spotifactory.tasks.base import Done, Step, TaskContext

    class BrokenStep(Step):
        def run(self, ctx):
            raise RuntimeError("simulated hardware failure")

    ctx = TaskContext(dry_run=False, data={})
    step = BrokenStep()
    step.start(ctx)
    assert _wait_for_done(step), "BrokenStep hung instead of surfacing the exception"
    assert isinstance(step.outcome, Done)
