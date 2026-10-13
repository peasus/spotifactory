# Spotifactory: notes for AI assistants

See `README.md` for what the project is, the hardware and the setup.

## Architecture
- `runner.py` is the platform-independent loop. Platforms (`platforms/seengreat.py`,
  `platforms/pi.py`, `platforms/sim.py`) call `handle_*()`, `tick()` and `render()`.
- Work happens in **Tasks** made of **Steps** (`tasks/base.py`). Each step's `run()`
  executes on a background thread and returns `Continue`, `PushMenu`, `Done` or
  `Cancel`. Steps show progress through `status`, plus optional `artist` and
  `detail` lines. Long-running steps expose `cancel()`; Back/Left calls it.
- `tasks/home/steps.py` is the home screen: it watches the NFC reader (nfcpy
  supervision mode) and starts or pauses Spotify playback.
- Settings chosen on the device (speaker, printer, BT MACs) are saved to `.env`
  with `settings.save_setting()`.
- Spotify login: on the Pi, PKCE through the Cloudflare relay in `deploy/relay/`
  (QR code). It never prompts on the terminal (`spotify._DevicePKCE`).

## Conventions
- Hardware imports happen inside functions, so tests and the simulator run on a Mac
  (`tests/conftest.py` stubs RPi/luma modules).
- The display is 128×64; long text scrolls automatically, so don't truncate strings.
- Run `.venv/bin/python -m pytest -q` before committing. The enclosure model has its own
  checks: `enclosure/.venv/bin/python enclosure/check.py`.
