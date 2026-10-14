# Spotifactory

A Raspberry Pi music box that plays albums from instant photos. Print an
album's cover on an Instax Square printer, stick an NFC tag on the back, and
from then on standing that photo on Spotifactory plays the album; lifting it
off pauses.

## How it works

- **Raspberry Pi Zero 2 W** with a **SeenGreat 1.3" OLED HAT** (SH1106 screen,
  5-way joystick) runs the app (`spotifactory.startup`) as a systemd service.
- A **PN532 NFC reader** (USB-C, CH340 serial) behind the photo reads the
  tag's `spotify:album:` / `spotify:playlist:` URI and starts playback through
  the Spotify Web API.
- Music plays on whichever speaker you pick in **Choose Speaker** (remembered
  across restarts), or by default on the Pi itself via **Raspotify**
  (librespot, shown in the Spotify app as "Spotifactory") and a paired
  Bluetooth speaker.
- **Print Album / Print Playlist** prints the current artwork on a paired
  **Instax Square Link** and then writes the tag.
- First-run setup needs no keyboard: a captive portal (Balena WiFi Connect)
  for WiFi, then a QR code that logs in to Spotify through a small Cloudflare
  Worker relay (`deploy/relay/`, PKCE — no client secret on the device).

## Controls

| Screen | Up | Down | Left / Right | Press |
|---|---|---|---|---|
| Home (now playing) | open menu | shuffle on/off | previous / next track | — |
| Menus | move | move | back / select | select |
| Running tasks | — | — | Left cancels where possible | — |

Menus return to the home screen after a minute idle (tags only work there),
and the screen sleeps after ten minutes with nothing playing.

## Setting up a Pi

1. Flash Raspberry Pi OS Lite (64-bit) with hostname `spotifactory`, user
   `spotifactory`, SSH and WiFi set in Imager.
2. On the Pi:
   ```
   sudo apt-get update && sudo apt-get install -y git
   git clone https://github.com/peasus/spotifactory.git ~/spotifactory
   cd ~/spotifactory && bash deploy/setup.sh
   ```
3. Set `SPOTIPY_CLIENT_ID` in `~/spotifactory/.env` (only that line; see
   `deploy/env.example`).
4. Reboot, scan the QR code to log in, then in the Spotify app pick the
   **Spotifactory** device once. Use **Pair Device** for the speaker and printer.

To deploy an update: `cd ~/spotifactory && git pull && sudo systemctl restart spotifactory`
(the setup script allows that restart without a password). Logs:
`journalctl -u spotifactory -f`.

## Development (Mac)

```
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q          # tests
.venv/bin/spotifactory --sim           # Tk simulator (arrow keys, Enter, T = fake tag)
```

On a Mac, put `SPOTIPY_CLIENT_SECRET` and `SPOTIPY_REDIRECT_URI` in `.env` to
log in through the browser instead of the relay.

## Enclosure

`enclosure/` holds a parametric build123d model of the case: a body, a
faceplate and a base plate, designed to print without supports.

```
python3 -m venv enclosure/.venv && enclosure/.venv/bin/pip install build123d trimesh matplotlib networkx
enclosure/.venv/bin/python enclosure/easel.py   # renders + STL/STEP into enclosure/out/
enclosure/.venv/bin/python enclosure/check.py   # fit, assembly and printability checks
```

Parts to buy are in `enclosure/bom_digikey.csv` (DigiKey import), plus screws
and a spare micro-USB cable for the power lead:

- 4× M2.5×14 pan or button head: up through the Pi, spacers and HAT into the
  faceplate. The heads sit in the pockets on top of the base plate's posts,
  which are 5.5 mm wide and 2 mm deep, so socket-cap heads (2.5 mm tall) won't fit.
- 4× M2.5×8: USB-C power board to its bracket.
- 4× M3×6 flat (countersunk) head: base plate into the heat-set inserts in
  the body's corners.

## Layout

| Path | What |
|---|---|
| `src/spotifactory/runner.py` | Platform-independent UI loop: input, tasks, rendering |
| `src/spotifactory/tasks/` | Home screen, printing, speakers, Bluetooth pairing, Spotify login |
| `src/spotifactory/hardware/` | NFC reader, Instax printer, Bluetooth, Sonos |
| `src/spotifactory/platforms/` | SeenGreat HAT, Adafruit OLED and simulator front ends |
| `deploy/` | Pi setup script, systemd unit, auth relay Worker |
| `enclosure/` | Case model, checks and parts list |
| `docs/sonos.md` | What does and doesn't work with Sonos speakers |
