import time

from spotifactory.menu.catalog import MENUS
from spotifactory.input.seengreat import SeenGreatInput
from spotifactory.display.sh1106 import DisplaySH1106
from spotifactory.runner import Runner
from spotifactory.tasks.home import HomeTask


def main() -> None:
    display = DisplaySH1106()
    buttons = SeenGreatInput()
    runner = Runner(display, MENUS, dry_run=False, home_task_class=HomeTask)

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
            runner.render()
            time.sleep(0.05)
    finally:
        buttons.cleanup()


if __name__ == "__main__":
    main()
