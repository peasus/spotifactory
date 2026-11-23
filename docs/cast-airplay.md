# Google Cast and AirPlay speakers

Spotify only lists a Google Cast speaker (or Cast speaker group) while one of
its own apps is casting to it, and the Web API has no AirPlay at all. Spotify
says Cast speakers are found by its apps on the local network and never
reported back to its servers, so the box can't see them in Spotify's device
list.

So for these speakers the box plays the music itself, as it does for its
Bluetooth speaker, and [OwnTone](https://owntone.github.io/owntone-server/)
streams that audio on:

```
librespot (Raspotify) -> PipeWire sink "spotifactory_network" -> /srv/music/spotifactory (fifo)
                      -> OwnTone (pipe input, autostart) -> Cast / AirPlay speaker
```

- `deploy/upgrade.sh` installs OwnTone from its Raspberry Pi apt repo, writes
  `/etc/owntone.conf` from `deploy/owntone.conf` (API on localhost only, no
  local output, MPD off) and creates the fifo. A failed install doesn't fail
  the update; it's tried again next time.
- **Choose Speaker** adds the Cast and AirPlay speakers OwnTone has found
  (`/api/outputs`), after Spotify's list and Sonos. A speaker Spotify already
  lists (a Cast speaker someone is casting to from the Spotify app) keeps
  Spotify's own entry.
- Choosing one saves it (`SPOTIFACTORY_NETWORK_SPEAKER_ID`/`_NAME` in `.env`),
  makes the pipe sink PipeWire's default, selects the speaker in OwnTone, and
  moves Spotify playback to the box's own "Spotifactory" device. Choosing any
  other speaker (or Music Assistant mode) puts the audio back on the box's own
  speaker and deselects OwnTone's.
- Tags, buttons and volume work as for the Bluetooth speaker: Spotify sees the
  box playing. The route is re-checked before each tag and at startup, since
  PipeWire forgets the pipe sink when it restarts.

## Limits

- About 2 seconds of buffering, so lift-to-pause and skips lag a little.
- The Spotify app shows "Playing on Spotifactory", not the speaker's name.
- One speaker (or one Cast group) at a time.
- AirPlay speakers that want a PIN or password (Apple TV, HomePods with access
  limits) are left out until the box can pair with them.
- Untested on real speakers. Things to check: a Cast group, an AirPlay 2
  speaker, memory use on a Pi Zero 2 W, and that the pipe sink loads under
  PipeWire (`pactl list short sinks` shows `spotifactory_network`).

## Debugging

```
journalctl -u spotifactory -f | grep owntone
curl -s http://localhost:3689/api/outputs | python3 -m json.tool
pactl list short sinks
tail -f /var/log/owntone.log
```
