from spotifactory.menu.catalog import MENUS
from spotifactory.display.sim import DisplaySim
from spotifactory.runner import Runner
from spotifactory.tasks.home import HomeTask


def main() -> None:
    display = DisplaySim()
    runner = Runner(display, MENUS, dry_run=False, printer_dry_run=False, home_task_class=HomeTask)

    def on_key(event):
        key = event.keysym
        if key == "Up":
            runner.handle_up()
        elif key == "Down":
            runner.handle_down()
        elif key == "Left":
            runner.handle_left()
        elif key == "Right":
            runner.handle_right()
        elif key == "Return":
            runner.handle_select()
        elif key in ("BackSpace", "Escape"):
            runner.handle_back()
        elif key in ("t", "T"):
            runner.handle_tag_scan_sim()
        runner.tick()
        runner.render()

    def poll():
        runner.tick()
        runner.render()
        display.root.after(50, poll)

    display.root.bind("<Key>", on_key)
    runner.render()
    display.root.after(100, poll)
    display.root.mainloop()


if __name__ == "__main__":
    main()
