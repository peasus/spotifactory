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

A Pi set up before the Reboot/Shutdown menu items worked needs its sudo rule
updated once (asks for your password): `cd ~/spotifactory && bash deploy/sudoers.sh`

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
faceplate, a base plate, spacers and two reader keepers, all designed to print
without supports. There are also models for a print crate (`crate.py`) and a
tag-sticker dispenser (`dispenser.py`), and small fit-test prints
(`keeper_test.py`, `crate_test.py`).

```
python3 -m venv enclosure/.venv && enclosure/.venv/bin/pip install build123d trimesh matplotlib networkx
enclosure/.venv/bin/python enclosure/easel.py   # renders + STL/STEP into enclosure/out/
enclosure/.venv/bin/python enclosure/check.py   # fit, assembly and printability checks
```

Parts to buy are in `enclosure/bom_digikey.csv` (DigiKey import), plus screws
and a spare micro-USB cable for the power lead:

- 4× M2.5×14 pan or button head: up through the Pi, spacers and HAT into the
  faceplate. M2.5×16 also works with one of the printed 2 mm washers (second
  row of the spacers print) under each head. The heads sit in the pockets on
  top of the base plate's posts, which are 5.5 mm wide and 4 mm deep. Pan or
  button heads only: don't use countersunk heads.
- 4× M2.5×8: USB-C power board to its bracket.
- 2× M2.5×14 (pan or button head): the reader keepers into their posts. Not 12 (too little thread in the post) or 16 (runs past the pilot hole).

The reader's cable (USB-C at the reader, micro-USB at the Pi) can be a regular
straight cable: a USB-C plug up to 12.5 mm wide and 6.5 mm thick (plug and
strain relief up to 28 mm long), and any straight micro-USB plug at the Pi.

Assembly order, with the body upside down or on its back:

1. Plug the right-angle USB-C cable into the reader. Bring the reader in from
   below, antenna side to the panel. Slide it about 4 mm up the panel until its
   top corners are in the caps.
2. Put a keeper under each bottom corner and drive an M2.5×14 straight up
   through it into the post.
3. Screw the Pi stack to the faceplate. Plug in its cables, then fit it from
   below into the pocket under the screen window.
4. Fit the base plate (with the power board on its bracket) and screw it into
   the corner inserts.

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
