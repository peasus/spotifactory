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
            from spotifactory.spotify import get_devices
            devices = get_devices()
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
    def run(self, ctx: TaskContext) -> StepOutcome:
        device = ctx.data.get("selected")
        if not device:
            return Done()

        name = device.get("name", "device")
        if len(name) > 14:
            name = name[:13] + "…"

        if ctx.dry_run:
            self.show_for(f"Would switch to\n{name}", 2.0)
            return Done()

        self.status = "Switching..."
        try:
            from spotifactory.spotify import set_active_device, transfer_playback
            transfer_playback(device["id"])
            set_active_device(device["id"])
        except Exception as e:
            self.show_for(f"Error: {str(e)[:20]}", 3.0)
            return Done()

        self.show_for(f"Now on {name}", 2.0)
        return Done()
