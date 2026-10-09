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
            on_confirm=Continue(),
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
        save_setting("INSTAX_BT_ADDRESS", classic_mac)
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

        save_setting("SPOTIFACTORY_SPEAKER_MAC", mac)

        # Move any active librespot stream to the new sink (no restart needed)
        self.status = "Switching audio..."
        move_sink_inputs(mac)
        self.show_for(f"Paired! {name}", 2.0)
