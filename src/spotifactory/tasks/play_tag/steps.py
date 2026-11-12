from __future__ import annotations

from spotifactory.tasks.base import Continue, Done, Step, StepOutcome, TaskContext


_SIM_URI = "spotify:album:5Z9iiGl2FcIfa3BMiv6OIw"


class ScanStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        self.status = "Place tag..."
        if ctx.dry_run:
            import time
            time.sleep(1.0)
            ctx.data["uri"] = _SIM_URI
            return Continue()
        try:
            from spotifactory.hardware.rfid import read_card
            card = read_card()
        except Exception as exc:
            self.show_for(f"RFID error: {type(exc).__name__}", 3.0)
            return Done()
        if not card or "uri" not in card:
            self.show_for("No URI on tag", 3.0)
            return Done()
        from spotifactory import backend
        uri = backend.pick_uri(card.get("uris") or [card["uri"]])
        if not uri:
            self.show_for(backend.no_link()[0], 3.0)
            return Done()
        ctx.data["uri"] = uri
        return Continue()


class PlayStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        self.status = "Starting playback..."
        uri = ctx.data["uri"]
        from spotifactory import backend
        try:
            backend.start_tag(uri)
        except backend.NoSpeakerError:
            self.show_for("Choose Speaker first", 3.0)
            return Done()
        except Exception as e:
            self.show_for(f"Error: {str(e)[:20]}", 3.0)
            return Done()
        return Continue()


class DoneStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        self.show_for("Playing!", 2.0)
        return Done()
