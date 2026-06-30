from spotifactory.menu.catalog import MENUS
from spotifactory.menu.renderer_sim import DisplaySim
from spotifactory.runner import Runner


def main() -> None:
    display = DisplaySim(scale=6)
    runner = Runner(display, MENUS)

    def on_key(event):
        key = event.keysym
        if key == "Up":
            runner.handle_up()
        elif key == "Down":
            runner.handle_down()
        elif key == "Return":
            runner.handle_select()
        elif key in ("BackSpace", "Escape"):
            runner.handle_back()
        runner.render()

    def poll():
        runner.tick()
        runner.render()
        display.root.after(100, poll)

    display.root.bind("<Key>", on_key)
    runner.render()
    display.root.after(100, poll)
    display.root.mainloop()


if __name__ == "__main__":
    main()
