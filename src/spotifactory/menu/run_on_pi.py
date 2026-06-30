import time

from spotifactory.menu.catalog import MENUS
from spotifactory.menu.input_buttons import ButtonInput
from spotifactory.menu.renderer_oled import DisplayOLED
from spotifactory.runner import Runner


def main() -> None:
    display = DisplayOLED()
    buttons = ButtonInput()
    runner = Runner(display, MENUS)

    while True:
        action = buttons.read()
        if action == "Up":
            runner.handle_up()
        elif action == "Down":
            runner.handle_down()
        elif action == "Select":
            runner.handle_select()
        elif action == "Back":
            runner.handle_back()

        runner.tick()
        runner.render()
        time.sleep(0.05)


if __name__ == "__main__":
    main()
