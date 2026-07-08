import time

from spotifactory.menu.catalog import MENUS
from spotifactory.input.seengreat import SeenGreatInput
from spotifactory.display.sh1106 import DisplaySH1106
from spotifactory.runner import Runner
from spotifactory.tasks.home import HomeTask


def main(display=None) -> None:
    if display is None:
        display = DisplaySH1106()
    buttons = SeenGreatInput()
    runner = Runner(display, MENUS, dry_run=False, home_task_class=HomeTask)

    display_ok = True
    try:
        while True:
            action = buttons.read()
            if action == "Up":
                runner.handle_up()
            elif action == "Down":
                runner.handle_down()
            elif action == "Left":
                runner.handle_left()
            elif action == "Right":
                runner.handle_right()
            elif action == "Select":
                runner.handle_select()
            elif action == "Back":
                runner.handle_back()

            runner.tick()
            if display_ok:
                try:
                    runner.render()
                except Exception as e:
                    print(f"[display] render failed, disabling display: {e}", flush=True)
                    display_ok = False
            time.sleep(0.05)
    finally:
        buttons.cleanup()
        try:
            display.device.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    main()
