# Google Cast and AirPlay speakers

Spotify only lists a Google Cast speaker (or Cast speaker group) while one of
its own apps is casting to it, and the Web API has no AirPlay at all. Spotify
says Cast speakers are found by its apps on the local network and never
reported back to its servers, so the box can't see them in Spotify's device
list.

So for these speakers the box plays the music itself, as it does for its
Bluetooth speaker, and [OwnTone](https://owntone.github.io/owntone-server/) on
the box streams that audio on:

```
librespot (Raspotify) -> PipeWire sink "spotifactory_network" -> /srv/music/spotifactory (fifo)
                      -> OwnTone (pipe input)
                           -> AirPlay speaker (OwnTone's own AirPlay output)
                           -> http://<box>:3689/stream.mp3 <- Cast speaker or group
```

- **Cast** (`cast_direct.py`): the box finds Cast speakers and groups itself,
  with a "legacy unicast" mDNS query (sent from an ordinary port, so speakers
  answer straight back; RFC 6762 6.7). Choosing one starts Google's standard
  media player on it (pychromecast) pointed at OwnTone's MP3 stream, with no
  OwnTone speaker selected, then starts OwnTone's player (it leaves the pipe
  paused otherwise). Groups work because the group's leader fetches the one
  stream and Google keeps the group in sync.
- **AirPlay** (`owntone.py`): OwnTone finds the speakers and streams to them.
- `network_speakers.py` ties them together for Choose Speaker and tags.

Why direct queries for Cast: ordinary mDNS waits for *multicast* answers, and
some networks never deliver those to the Pi. On a friend's Google Wifi the
2.4 GHz-only Pi Zero 2 W heard no multicast from any speaker (Wi-Fi power
saving off), yet a Cast and an AirPlay speaker both answered a direct query.
Routers that separate the 2.4 and 5 GHz bands are a known cause. OwnTone (via
Avahi) can only use multicast, so AirPlay speakers on such networks aren't
found yet; relaying direct answers into Avahi is the next step.

## Install (`deploy/upgrade.sh`)

- OwnTone from its Raspberry Pi apt repo, run as its own `owntone` user,
  config from `deploy/owntone.conf` (API on localhost only, no local output,
  MPD off), and the fifo. A failed install doesn't fail the update.
- `pulseaudio-utils` for `pactl` (pipewire-pulse doesn't ship it).
- Wi-Fi power saving off (`deploy/nm-wifi-powersave.conf`, and `iw` on the
  live interface): it drops multicast and makes streaming stutter.
- `pychromecast` (pyproject).

## Choosing

- **Choose Speaker** lists Spotify's devices, then Sonos, then Cast speakers
  found directly and OwnTone's AirPlay speakers. A speaker Spotify already
  lists (a Cast speaker someone is casting to from the Spotify app) keeps
  Spotify's own entry.
- Choosing one saves it (`SPOTIFACTORY_NETWORK_SPEAKER_ID`/`_NAME` in `.env`),
  points PipeWire at the pipe and moves Spotify playback to the box's own
  "Spotifactory" device. Choosing any other speaker (or Music Assistant mode)
  puts the audio back on the box's own speaker and stops the network one.
- Each tag re-checks the route (PipeWire forgets the pipe sink when it
  restarts) and, a moment after playback starts, that the Cast speaker is
  still playing the stream (it goes idle when the stream stops after a pause).

## Limits

- Cast lags a few seconds (the stream is buffered); AirPlay about 2 seconds.
- The Spotify app shows "Playing on Spotifactory", not the speaker's name.
- One speaker (or one Cast group) at a time.
- AirPlay speakers that want a PIN or password (Apple TV, HomePods with access
  limits) are left out until the box can pair with them.

## Debugging

```
journalctl -u spotifactory -f | grep -E "cast|owntone|speakers"
curl -s http://localhost:3689/api/outputs | python3 -m json.tool
curl -s http://localhost:3689/api/player
pactl list short sinks
tail -f /var/log/owntone.log
```
