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
            from spotifactory.hardware.rfid import read_card
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
            from spotifactory.spotify import get_playback_device_id
            sp = get_client()
            sp.start_playback(context_uri=uri, device_id=get_playback_device_id())
        except spotipy.SpotifyException as e:
            if "device" in str(e).lower() or "restricted" in str(e).lower():
                self.show_for("Choose Speaker first", 3.0)
            else:
                self.show_for("Spotify error", 3.0)
            return Done()
        except Exception as e:
            self.show_for(f"Error: {str(e)[:20]}", 3.0)
            return Done()
        return Continue()


class DoneStep(Step):
    def run(self, ctx: TaskContext) -> StepOutcome:
        self.show_for("Playing!", 2.0)
        return Done()
