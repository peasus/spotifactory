from __future__ import annotations

import spotipy

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
            from spotifactory.rfid import read_card
            card = read_card()
        except Exception as exc:
            self.show_for(f"RFID error: {type(exc).__name__}", 3.0)
            return Done()
        if not card or "uri" not in card:
            self.show_for("No URI on tag", 3.0)
            return Done()
        ctx.data["uri"] = card["uri"]
        return Continue()


class PlayStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        from spotifactory.spotify import get_client
        self.status = "Starting playback..."
        uri = ctx.data["uri"]
        try:
            sp = get_client()
            sp.start_playback(context_uri=uri)
        except spotipy.SpotifyException as e:
            msg = "No active device" if "device" in str(e).lower() else "Spotify error"
            self.show_for(msg, 3.0)
            return Done()
        except Exception as e:
            self.show_for(f"Error: {str(e)[:20]}", 3.0)
            return Done()
        return Continue()


class DoneStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        self.show_for("Playing!", 2.0)
        return Done()
