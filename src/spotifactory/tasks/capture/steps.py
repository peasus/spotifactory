from __future__ import annotations

from io import BytesIO

import requests

from spotifactory.tasks.base import (
    Cancel,
    Continue,
    Done,
    PushMenu,
    Step,
    StepOutcome,
    TaskContext,
)


def _confirm_menu(album_name: str):
    from spotifactory.menu.definitions import ItemDef, MenuDef
    return MenuDef(album_name, [
        ItemDef("Yes", action="confirm"),
        ItemDef("No",  action="cancel"),
    ], visible_rows=2)


def _printer_off_menu():
    from spotifactory.menu.definitions import ItemDef, MenuDef
    return MenuDef("Printer Off?", [
        ItemDef("Retry",  action="confirm"),
        ItemDef("Cancel", action="cancel"),
    ], visible_rows=2)


class FetchInfoStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        from spotifactory.spotify import get_now_playing
        self.status = "Checking Spotify..."
        info = get_now_playing()
        if info is None:
            self.show_for("Nothing playing", 2.0)
            return Done()
        ctx.data["info"] = info
        return Continue()


class ConfirmStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        info = ctx.data["info"]
        return PushMenu(
            menu=_confirm_menu(info.album_name),
            on_confirm=Continue(),
            on_cancel=Cancel(),
        )


class FetchArtStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        self.status = "Fetching artwork..."
        try:
            url = ctx.data["info"].artwork_url
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            ctx.data["image"] = BytesIO(resp.content)
        except Exception as e:
            self.show_for(f"Art error: {str(e)[:20]}", 3.0)
            return Done()
        return Continue()


class PrintStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        from spotifactory.printer import print_image
        self.status = "Printing..."
        result = print_image(ctx.data["image"], dry_run=ctx.dry_run)
        ctx.data["print_result"] = result

        if not result.printer_found:
            return PushMenu(
                menu=_printer_off_menu(),
                on_confirm=Continue(next_step="print"),  # retry
                on_cancel=Cancel(),
            )
        if not result.success and not ctx.dry_run:
            self.show_for("Print failed", 3.0)
            return Done()
        return Continue()


class ScanStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        from spotifactory.rfid import write_uri
        self.status = "Please scan tag"
        try:
            write_uri(ctx.data["info"].album_uri)
        except Exception as e:
            self.show_for(f"RFID error: {str(e)[:20]}", 3.0)
            return Done()
        return Continue()


class DoneStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        result = ctx.data.get("print_result")
        photos = f"{result.photos_left} photos left" if result else ""
        self.show_for(f"Album ready! {photos}".strip(), 3.0)
        return Done()
