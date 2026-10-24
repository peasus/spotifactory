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


def _sonos_devices(listed: list[dict]) -> list[dict]:
    """Sonos rooms Spotify didn't list (it hides them while idle), when the
    Connect helper is installed to play them (spotifactory/connect.py)."""
    from spotifactory import connect
    if not connect.available():
        return []
    try:
        from spotifactory.hardware.sonos import connect_speakers
        found = connect_speakers()
    except Exception as e:
        print(f"[speaker] Sonos discovery failed: {e}", flush=True)
        return []
    ids = {d.get("id") for d in listed}
    return [d for d in found if d["id"] not in ids]


class FetchDevicesStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        self.status = "Finding devices..."
        try:
            from spotifactory.spotify import get_devices
            devices = get_devices()
        except Exception as e:
            self.show_for(f"Error: {str(e)[:20]}", 3.0)
            return Done()
        devices = devices + _sonos_devices(devices)

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

        from spotifactory.spotify import set_active_device, transfer_playback

        # Save first: the choice stands even if the speaker is asleep right now
        # (idle Echos are listed but return 404 until something wakes them).
        restricted = bool(device.get("is_restricted"))
        set_active_device(device["id"], name, restricted=restricted)

        self.status = "Switching..."
        try:
            transfer_playback(device["id"], restricted=restricted)
        except Exception as e:
            print(f"[speaker] transfer to {name!r} failed: {e}", flush=True)
            self.artist = "Not responding now"
            self.show_for(f"Saved: {name}", 3.0)
            return Done()

        self.show_for(f"Now on {name}", 2.0)
        return Done()
