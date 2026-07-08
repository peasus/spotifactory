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
    return MenuDef("Pair Speaker", items, visible_rows=4)


def _device_label(d: dict) -> str:
    name = d.get("name", d.get("mac", "Unknown"))
    if len(name) > 18:
        name = name[:17] + "…"
    return name


def _find_env_path() -> str:
    """Return the path to the project .env file."""
    import pathlib
    # Walk up from this file until we find pyproject.toml
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
        if len(name) > 14:
            name = name[:13] + "…"

        if ctx.dry_run:
            self.show_for(f"Would pair {name}", 2.0)
            return Done()

        self.status = f"Pairing {name}..."
        try:
            from spotifactory.hardware.bluetooth import pair_and_configure, write_asoundrc
            pair_and_configure(mac)
            write_asoundrc(mac)
        except Exception as e:
            print(f"[bluetooth] pair_and_configure error: {e}", flush=True)
            self.show_for(str(e)[:20], 3.0)
            return Done()

        # Persist MAC to .env for auto-reconnect on boot
        try:
            from dotenv import set_key
            set_key(_find_env_path(), "SPOTIFACTORY_SPEAKER_MAC", mac)
        except Exception:
            pass

        # Restart Raspotify so it picks up the new ALSA default
        self.status = "Restarting audio..."
        try:
            subprocess.run(
                ["sudo", "systemctl", "restart", "raspotify"],
                check=True, capture_output=True,
            )
        except Exception:
            pass  # non-fatal — Raspotify will use the new config on next restart

        self.show_for(f"Paired! {name}", 2.0)
        return Done()
