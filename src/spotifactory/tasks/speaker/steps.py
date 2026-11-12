from __future__ import annotations

from spotifactory.tasks.base import (
    Cancel,
    Continue,
    Done,
    PushMenu,
    Step,
    StepOutcome,
    TaskContext,
)


def _devices_menu(devices: list[dict]):
    from spotifactory.menu.definitions import ItemDef, MenuDef
    items = [
        ItemDef(
            label=_device_label(d),
            action="confirm",
            data=d,
        )
        for d in devices
    ]
    items.append(ItemDef("Cancel", action="cancel"))
    return MenuDef("Choose Speaker", items, visible_rows=4)


def _device_label(d: dict) -> str:
    name = d.get("name", "Unknown")
    return f"{name} *" if d.get("is_active") else name


class FetchDevicesStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        self.status = "Finding devices..."
        try:
            from spotifactory import backend
            devices = backend.list_speakers()
        except Exception as e:
            self.show_for(f"Error: {str(e)[:20]}", 3.0)
            return Done()

        if not devices:
            self.show_for("No devices found", 2.0)
            return Done()

        ctx.data["devices"] = devices
        return PushMenu(
            menu=_devices_menu(devices),
            on_confirm=Continue(),
            on_cancel=Cancel(),
        )


class SetDeviceStep(Step):
    def __init__(self) -> None:
        super().__init__()
        self.artist: str = ""

    def run(self, ctx: TaskContext) -> StepOutcome:
        device = ctx.data.get("selected")
        if not device:
            return Done()

        name = device.get("name", "device")

        if ctx.dry_run:
            self.artist = name
            self.show_for("Would switch to", 2.0)
            return Done()

        from spotifactory import backend

        self.status = "Switching..."
        try:
            backend.choose_speaker(device)   # saved even if the move fails
        except Exception as e:
            print(f"[speaker] transfer to {name!r} failed: {e}", flush=True)
            self.artist = "Not responding now"
            self.show_for(f"Saved: {name}", 3.0)
            return Done()

        self.show_for(f"Now on {name}", 2.0)
        return Done()
