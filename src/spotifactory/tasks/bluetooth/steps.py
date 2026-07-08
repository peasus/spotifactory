from __future__ import annotations

import subprocess

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
    name = d.get("name", d.get("mac", "Unknown"))
    if len(name) > 18:
        name = name[:17] + "…"
    return name


def _find_env_path() -> str:
    import pathlib
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return str(parent / ".env")
    return ".env"


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

        from spotifactory.hardware.bluetooth import (
            is_instax, instax_classic_addr, pair_and_configure, set_bt_audio_output,
        )
        from dotenv import set_key

        if is_instax(device):
            self._pair_printer(mac, short_name, instax_classic_addr, pair_and_configure, set_key)
        else:
            self._pair_speaker(mac, short_name, pair_and_configure, set_bt_audio_output, set_key)

        return Done()

    def _pair_printer(self, ios_mac, name, instax_classic_addr, pair_and_configure, set_key):
        classic_mac = instax_classic_addr(ios_mac)
        self.status = f"Pairing {name}..."
        try:
            pair_and_configure(classic_mac)
        except Exception as e:
            print(f"[bluetooth] instax pair error: {e}", flush=True)
            self.show_for(str(e)[:20], 3.0)
            return

        try:
            set_key(_find_env_path(), "INSTAX_BT_ADDRESS", classic_mac)
        except Exception:
            pass

        self.show_for(f"Printer ready!", 2.0)

    def _pair_speaker(self, mac, name, pair_and_configure, set_bt_audio_output, set_key):
        self.status = f"Pairing {name}..."
        try:
            pair_and_configure(mac)
            set_bt_audio_output(mac)
        except Exception as e:
            print(f"[bluetooth] speaker pair error: {e}", flush=True)
            self.show_for(str(e)[:20], 3.0)
            return

        try:
            set_key(_find_env_path(), "SPOTIFACTORY_SPEAKER_MAC", mac)
        except Exception:
            pass

        # Move any active librespot stream to the new sink (no restart needed)
        self.status = "Switching audio..."
        try:
            result = subprocess.run(
                ["pactl", "list", "sink-inputs", "short"],
                capture_output=True, text=True, timeout=5,
            )
            sink_name = "bluez_output." + mac.replace(":", "_") + ".1"
            for line in result.stdout.splitlines():
                parts = line.split()
                if parts:
                    subprocess.run(
                        ["pactl", "move-sink-input", parts[0], sink_name],
                        capture_output=True, timeout=5,
                    )
        except Exception:
            pass

        self.show_for(f"Paired! {name}", 2.0)
