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

SPEAKER_KEY = "SPOTIFACTORY_SPEAKER_MAC"
PRINTER_KEY = "INSTAX_BT_ADDRESS"
_PAIR_NEW = {"action": "pair_new"}


def _short(name: str, n: int = 14) -> str:
    return name[:n - 1] + "…" if len(name) > n else name


def _saved(key: str) -> str:
    import os
    return os.environ.get(key, "").strip().upper()


def _role(device: dict) -> str:
    """"speaker" (the box's speaker), "printer", "audio" (another speaker) or ""."""
    mac = device["mac"].upper()
    if mac == _saved(SPEAKER_KEY):
        return "speaker"
    if mac == _saved(PRINTER_KEY) or device.get("name", "").upper().startswith("INSTAX"):
        return "printer"
    return "audio" if device.get("audio") else ""


def _state(device: dict) -> str:
    """One line on the device: what it's for, and whether it's connected."""
    role = {"speaker": "In use", "printer": "Printer"}.get(_role(device), "Paired")
    if _role(device) == "printer":
        return role
    return f"{role} - {'connected' if device.get('connected') else 'not connected'}"


def _devices_menu(devices: list[dict]):
    from spotifactory.menu.definitions import ItemDef, MenuDef
    items = []
    for d in devices:
        mark = " *" if d.get("connected") else ""
        items.append(ItemDef(label=_short(d["name"], 17) + mark, action="confirm", data=d))
    items.append(ItemDef("+ Pair new device", action="confirm", data=_PAIR_NEW))
    items.append(ItemDef("Back", action="cancel"))
    subtitle = "* = connected" if any(d.get("connected") for d in devices) else None
    return MenuDef("Bluetooth", items, visible_rows=4, subtitle=subtitle)


def _device_actions_menu(device: dict):
    from spotifactory.menu.definitions import ItemDef, MenuDef
    role = _role(device)
    items = []
    if role in ("speaker", "audio") and not (role == "speaker" and device.get("connected")):
        items.append(ItemDef("Use as speaker" if role == "audio" else "Connect",
                             action="confirm", data={"action": "use"}))
    if device.get("connected") and role != "speaker":
        items.append(ItemDef("Disconnect", action="confirm", data={"action": "disconnect"}))
    items.append(ItemDef("Forget", action="confirm", data={"action": "forget"}))
    items.append(ItemDef("Back", action="cancel"))
    return MenuDef(_short(device["name"], 18), items, visible_rows=4, subtitle=_state(device))


def _confirm_forget_menu(device: dict):
    from spotifactory.menu.definitions import ItemDef, MenuDef
    return MenuDef(f"Forget {_short(device['name'], 11)}?", [
        ItemDef("Cancel", action="cancel"),
        ItemDef("Forget", action="confirm", data={"action": "forget_now"}),
    ], visible_rows=2, subtitle="Pair again to use it")


class DevicesStep(Step):
    """Paired devices and their state, then "+ Pair new device"."""

    def run(self, ctx: TaskContext) -> StepOutcome:
        self.status = "Bluetooth..."
        try:
            from spotifactory.hardware.bluetooth import paired_devices
            devices = paired_devices()
        except Exception as e:
            print(f"[bluetooth] paired list: {e}", flush=True)
            devices = []
        ctx.data["bt_paired"] = devices
        return PushMenu(menu=_devices_menu(devices),
                        on_confirm=Continue("chosen"), on_cancel=Cancel())


class ChosenStep(Step):
    """A device was picked: its actions, or the pairing scan."""

    def run(self, ctx: TaskContext) -> StepOutcome:
        picked = ctx.data.get("selected")
        if not picked or picked == _PAIR_NEW:
            return Continue("scan")
        ctx.data["bt_device"] = picked
        return PushMenu(menu=_device_actions_menu(picked),
                        on_confirm=Continue("act"), on_cancel=Continue("devices"))


class ActStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        device = ctx.data.get("bt_device") or {}
        action = (ctx.data.get("selected") or {}).get("action")
        mac, name = device.get("mac", ""), _short(device.get("name", ""))
        if not mac:
            return Done()
        if action == "forget":
            return PushMenu(menu=_confirm_forget_menu(device),
                            on_confirm=Continue("act"), on_cancel=Continue("devices"))
        if ctx.dry_run:
            self.show_for(f"Would {action} {name}", 2.0)
            return Continue("devices")
        from spotifactory.hardware import bluetooth as bt
        from spotifactory.settings import save_setting
        if action == "use":
            self.status = f"Connecting {name}..."
            bt.reconnect(mac)
            if not bt.is_connected(mac):
                self.show_for("Turn it on, try again", 3.0)
                return Continue("devices")
            bt.set_bt_audio_output(mac)
            save_setting(SPEAKER_KEY, mac)
            bt.move_sink_inputs(mac)
            self.show_for(f"Using {name}", 2.0)
        elif action == "disconnect":
            self.status = f"Disconnecting {name}..."
            bt.disconnect(mac)
        elif action == "forget_now":
            self.status = f"Forgetting {name}..."
            if not bt.forget(mac):
                self.show_for("Couldn't forget it", 2.0)
                return Continue("devices")
            for key in (SPEAKER_KEY, PRINTER_KEY):
                if _saved(key) == mac.upper():
                    save_setting(key, "")         # the reconnect loop lets it go too
            self.show_for(f"Forgot {name}", 2.0)
        return Continue("devices")


def _bt_devices_menu(devices: list[dict]):
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
    return MenuDef("Pair Device", items, visible_rows=4)


def _device_label(d: dict) -> str:
    return d.get("name", d.get("mac", "Unknown"))


class ScanStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        self.status = "Scanning BT (10s)..."
        try:
            from spotifactory.hardware.bluetooth import scan_devices
            devices = scan_devices(timeout=10)
        except Exception as e:
            self.show_for(f"BT error: {str(e)[:20]}", 3.0)
            return Done()

        if not devices:
            self.show_for("No devices found", 2.0)
            return Done()

        ctx.data["bt_devices"] = devices
        return PushMenu(
            menu=_bt_devices_menu(devices),
            on_confirm=Continue("pair"),
            on_cancel=Cancel(),
        )


class PairStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        device = ctx.data.get("selected")
        if not device:
            return Done()

        mac = device["mac"]
        name = device.get("name", mac)
        short_name = name[:13] + "…" if len(name) > 14 else name

        if ctx.dry_run:
            self.show_for(f"Would pair {short_name}", 2.0)
            return Done()

        from spotifactory.hardware.bluetooth import is_instax

        if is_instax(device):
            self._pair_printer(mac, short_name)
        else:
            self._pair_speaker(mac, short_name)

        return Done()

    def _pair_printer(self, ios_mac, name):
        from spotifactory.hardware.bluetooth import instax_classic_addr, pair_and_configure
        from spotifactory.settings import save_setting

        classic_mac = instax_classic_addr(ios_mac)
        self.status = f"Pairing {name}..."
        try:
            pair_and_configure(classic_mac, connect=False)
        except Exception as e:
            print(f"[bluetooth] instax pair error: {e}", flush=True)
            self.show_for(str(e), 3.0)
            return

        # Applies now (printing skips the BLE scan) and on the next boot.
        save_setting(PRINTER_KEY, classic_mac)
        self.show_for("Printer ready!", 2.0)

    def _pair_speaker(self, mac, name):
        from spotifactory.hardware.bluetooth import (
            move_sink_inputs,
            pair_and_configure,
            set_bt_audio_output,
        )
        from spotifactory.settings import save_setting

        self.status = f"Pairing {name}..."
        try:
            pair_and_configure(mac)
            set_bt_audio_output(mac)
        except Exception as e:
            print(f"[bluetooth] speaker pair error: {e}", flush=True)
            self.show_for(str(e), 3.0)
            return

        save_setting(SPEAKER_KEY, mac)

        # Move any active librespot stream to the new sink (no restart needed)
        self.status = "Switching audio..."
        move_sink_inputs(mac)
        self.show_for(f"Paired! {name}", 2.0)
