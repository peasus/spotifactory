from spotifactory.menu.catalog import MENUS
from spotifactory.display.sim import DisplaySim
from spotifactory.runner import Runner
from spotifactory.tasks.home import HomeTask


def main() -> None:
    display = DisplaySim()
    runner = Runner(display, MENUS, dry_run=False, printer_dry_run=True, home_task_class=HomeTask)
    release_timers = {}

    def on_key(event):
        key = event.keysym
        if key == "Up":
            runner.handle_up()
        elif key == "Down":
            runner.handle_down()
        elif key == "Left":
            runner.handle_left()
            runner.handle_release(-1)     # a key press skips; [ and ] scrub
        elif key == "Right":
            runner.handle_right()
            runner.handle_release(+1)
        elif key in ("bracketleft", "bracketright"):
            direction = -1 if key == "bracketleft" else +1
            runner.handle_seek_hold(direction)
            # Let go once the key stops repeating.
            if release_timers.get(direction):
                display.root.after_cancel(release_timers[direction])
            release_timers[direction] = display.root.after(
                400, lambda: runner.handle_release(direction))
        elif key == "Return":
            runner.handle_select()
        elif key in ("BackSpace", "Escape"):
            runner.handle_back()
        elif key in ("t", "T"):
            runner.handle_tag_scan_sim()
        elif key in ("plus", "equal", "KP_Add"):
            runner.handle_volume(+1)
        elif key in ("minus", "KP_Subtract"):
            runner.handle_volume(-1)
        elif key in ("m", "M"):
            runner.handle_menu()
        elif key == "space":
            runner.handle_play_pause()
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
