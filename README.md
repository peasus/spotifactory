# Spotifactory

[spotifactory.com](https://spotifactory.com) · website source in `site/` (see `docs/website.md`)

A Raspberry Pi music box that plays albums from instant photos. Print an
album's cover on an Instax Square printer, stick an NFC tag on the back, and
from then on standing that photo on Spotifactory plays the album; lifting it
off pauses.

## How it works

- **Raspberry Pi Zero 2 W** with a **SeenGreat 1.3" OLED HAT** ([this one](https://a.co/d/09jW1LQh); SH1106 screen,
  5-way joystick) runs the app (`spotifactory.startup`) as a systemd service.
- A **PN532 NFC reader** (USB-C, CH340 serial; [this one](https://a.co/d/0b7JEN1F)) behind the photo reads the
  tag's `spotify:album:` / `spotify:playlist:` URI and starts playback through
  the Spotify Web API.
- Music plays on whichever speaker you pick in **Choose Speaker** (remembered
  across restarts), or by default on the Pi itself via **Raspotify**
  (librespot, shown in the Spotify app as "Spotifactory") and a paired
  Bluetooth speaker.
- **Print Album / Print Playlist** prints the current artwork on a paired
  **Instax Square Link** and then writes the tag. **Film Left** asks the
  printer how many shots are left in the pack (and its battery).
- First-run setup needs no keyboard: a Spotifactory-branded captive portal
  (Balena WiFi Connect serving `deploy/portal/`) for WiFi, then a QR code that logs in to Spotify through a small Cloudflare
  Worker relay (`deploy/relay/`, PKCE — no client secret on the device).

## Controls

| Screen | Up | Down | Left / Right | Press |
|---|---|---|---|---|
| Home (now playing) | repeat: off → album → track | shuffle on/off | tap: previous / next track; hold: scrub through the track | display: now playing → time → album |
| Menus | move | move | back / select | select |
| Running tasks | — | — | Left cancels where possible | — |

The three buttons beside the screen, top to bottom: volume up, volume down
(both repeat when held), and menu, which opens the menu from home and goes
straight back to home from anywhere in it (over a prompt it's Back). There's
no pause button: lift the album off to pause, put it back to carry on.

Menus return to the home screen after a minute idle (tags only work there),
and the screen sleeps after ten minutes with nothing playing.

## Setting up a Pi

Once, on your computer: copy `deploy/provision.env.example` to
`deploy/provision.env` (git-ignored) and fill in your Spotify client ID. Setup
merges it into each box's `.env`, so nothing needs editing on the Pi.

1. Flash Raspberry Pi OS Lite (64-bit) with hostname `spotifactory`, user
   `spotifactory`, SSH and WiFi set in Imager.
2. From your computer, copy your values over:
   ```
   scp deploy/provision.env spotifactory@spotifactory.local:~/spotifactory-provision.env
   ```
3. On the Pi:
   ```
   sudo apt-get update && sudo apt-get install -y git
   git clone https://github.com/peasus/spotifactory.git ~/spotifactory
   cd ~/spotifactory && bash deploy/setup.sh
   ```
4. Reboot, scan the QR code to log in, then in the Spotify app pick the
   **Spotifactory** device once. Use **Pair Device** for the speaker and printer.

Logs: `journalctl -u spotifactory -f`.

### Updates

Boxes update themselves from the **`stable`** branch: each night around 3:30
(skipped while someone's using it), or from the menu with **Check for
Updates**. To release, try it on your own box first, then:

```
git push origin main:stable
```

Each update pulls the code, reinstalls Python packages if `pyproject.toml`
changed, runs `deploy/upgrade.sh` (service files and the sudo rule, so those
reach boxes in the field too), and restarts the app. If the app doesn't come
back within two minutes it rolls back, and won't try that release again. To
update one now over SSH: `sudo systemctl start spotifactory-update`; to see what
happened: `journalctl -u spotifactory-update -n 30`.

Your development box can follow `main` (`SPOTIFACTORY_UPDATE_BRANCH=main` in
`.env`) or skip the nightly run (`SPOTIFACTORY_AUTO_UPDATE=0`). Note that a box
that has updated is on a detached checkout, not a branch: update it with the
updater rather than `git pull`.

A Pi set up before the updater existed needs the system part installed once
(asks for your password): `cd ~/spotifactory && git pull && sudo bash deploy/upgrade.sh`

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

### Printing

Printed in PLA on a Bambu P1S (0.4 mm nozzle) with Bambu Studio's Generic PLA
filament profile, at 0.12 mm layers. The STLs come out already oriented for
the bed. Settings that matter:

- **Wall loops 4–5** (body especially). The screw posts have about 1.7 mm of
  plastic round each pilot hole; with 4 walls that's solid plastic rather
  than infill, so screws hold instead of stripping.
- **Body: inner brim, plus brim ears on the outside of the back corners.** It
  stands on its thin walls and is tall, so the corners tend to lift. Brim type
  "Inner brim only" (or "Painted") keeps the outer chamfer clean; a brim-object
  gap of 0.1 mm makes it peel off easily.
- **Against warping:** auxiliary part cooling fan 0% (on a P1S it blows across
  the left of the bed), door and lid closed, no cooling for the first 3
  layers, bed 60 °C (65 °C first layer), and the part in the middle of the
  plate. Wash the plate with dish soap first.
- **Screws into printed plastic:** stop as soon as the head is snug. A
  quarter-turn more strips PLA.

Parts to buy are in `enclosure/BOM.md`, with DigiKey and Mouser part numbers
and what neither distributor carries. `enclosure/bom_digikey.csv` and
`enclosure/bom_mouser.csv` import straight into either cart. The screws:

- 4× M2.5×14 pan or button head: up through the Pi, spacers and HAT into the
  faceplate. M2.5×16 also works with one of the printed 2 mm washers (second
  row of the spacers print) under each head. The heads sit in the pockets on
  top of the base plate's posts, which are 5.5 mm wide and 4 mm deep. Pan or
  button heads only: don't use countersunk heads.
- 4× M2.5×8: USB-C power board to its bracket.
- 2× M2.5×20 (pan or button head): the reader keepers into their posts.
  16 or 18 also work, with less thread in the post; not 22 or longer (runs
  past the pilot hole).

The reader's cable (USB-C at the reader, micro-USB at the Pi) can be a regular
straight cable: a USB-C plug up to 12.5 mm wide and 6.5 mm thick (plug and
strain relief up to 28 mm long), and any straight micro-USB plug at the Pi.

Before assembly, set the screen HAT to I2C: both switches on its back (SW1,
SW2) to 0. The app talks to the screen over I2C only (at 400 kHz, which setup
configures).

Assembly order, with the body upside down or on its back:

1. Plug the right-angle USB-C cable into the reader. Bring the reader in from
   below, antenna side to the panel. Slide it about 4 mm up the panel until its
   top corners are in the caps.
2. Put a keeper under each bottom corner and drive an M2.5×20 straight up
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
| `connect-helper/` | Rust helper that plays Spotify on Sonos speakers (experimental) |
| `docs/sonos.md` | What does and doesn't work with Sonos speakers |

## License

Spotifactory, the app and the enclosure, is © 2025–2026 Joe Pease, under the
[PolyForm Noncommercial License 1.0.0](LICENSE.md): free to use, change and
share for personal and other noncommercial purposes. Selling it, or using it
commercially, needs permission: ask at hello@spotifactory.com.

`src/spotifactory/vendor/instax/` is from
[InstaxBLE](https://github.com/javl/InstaxBLE) by Jasper van Loenen, under its
own [MIT license](src/spotifactory/vendor/instax/LICENSE.md).
