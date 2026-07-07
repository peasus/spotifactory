# Sonos Integration Status

## What works

**Pause / resume via SoCo UPnP** — reliable on all Sonos hardware during an active Spotify
Connect session. `coordinator.pause()` and `coordinator.play()` work regardless of firmware.
This is what Spotifactory uses: tag removed → SoCo pause; tag placed again → SoCo resume
(if the user has already started playback manually).

## What doesn't work and why

### Starting playback programmatically

Two paths were exhaustively tested and both are blocked:

**Path 1 — Spotify Web API (`start_playback`, `transfer_playback`):**
All Sonos speakers return `"is_restricted": true` in the Spotify devices API. Spotify rejects
every Web API command to a restricted device with HTTP 403, regardless of OAuth scopes or
whether a device_id is specified. This applies to all Sonos hardware on all firmware versions.

**Path 2 — SoCo native SMAPI streaming (`AddURIToQueue` + `x-sonos-spotify:` URIs):**
Sonos S2 firmware 82.2-59204 (released December 2024) disabled this path. Calling
`avTransport.AddURIToQueue` with a Spotify URI returns UPnP Error 800 on all S2 hardware.
This was confirmed on ERA 100, Beam, and Arc Ultra — the error is S2-wide, not model-specific.
S1 hardware is unaffected, but no S1 speakers were available to test against.

The root cause is Sonos progressively moving S2 to Spotify Connect as the only supported
integration path, with the December 2024 firmware completing that transition.

### Detection note

`systemProperties.GetString("R_Svc3079_SerialNum")` returns Error 800 (variable not found) on
all speakers in this household. This variable would contain the SMAPI credential serial number
if native streaming were provisioned. Its absence confirms that SMAPI Spotify is not available,
regardless of hardware model.

## Approaches investigated but not implemented

### Spotify Zeroconf `addUser`

Sonos speakers advertise a `_spotify-connect._tcp` service (port 1400, path `/spotifyzc`).
The `getInfo` endpoint returns `"tokenType": "authorization_code"`, which means `addUser`
requires a Spotify Desktop App OAuth token (client_id `65b708073fc0480ea92a077233ca87bd`),
not a standard third-party PKCE token. Exchanging our token via RFC 8693 token-exchange was
rejected. Even if `addUser` succeeded and put the speaker in Connect mode, we still have no
way to load specific content — both the Web API and SMAPI paths are blocked.

The `spotifywebapipython` library (`pip install spotifywebapipython`) implements this full flow
and would be the starting point if this becomes unblocked.

### sp_dc cookie + TOTP elevated token

Spotify's internal web player API (`open.spotify.com/get_access_token`) issues tokens with
broader scope that may bypass the `is_restricted` check. Since March 2025 this requires a
TOTP value derived from a cipher embedded in Spotify's JavaScript bundle. Libraries that
implement this: `spotifywebapipython` (`SpotifyWebPlayerToken` class).

Not implemented for Spotifactory because:
- `sp_dc` cookies expire annually and require manual browser extraction to refresh
- The TOTP cipher rotates when Spotify updates their web player JS bundle
- Spotify has issued C&Ds to projects publishing the cipher and broken the flow multiple times
- Not a stable foundation for a gift device

Even with an elevated token, loading specific content to a Sonos speaker requires the
internal `spclient connect-state/v1/connect/transfer` endpoint — not the public API.

## What to watch for

This situation could change if:
- Sonos re-enables SMAPI Spotify on S2 firmware (they control this server-side, no code change needed)
- Spotify exposes a public API endpoint for Connect content control that works on restricted devices
- Sonos exposes a documented local HTTP API for content loading (they have one at port 1443 but it requires full OAuth)

The `pause_speaker()` function in `src/spotifactory/hardware/sonos.py` uses SoCo and will
continue to work through any of these changes. Play support can be added back by implementing
`play_spotify_uri()` once a viable path exists.

## References

- [SoCo issue #969](https://github.com/SoCo/SoCo/issues/969) — S2 Error 800 on AddURIToQueue
- [HA core issue #133052](https://github.com/home-assistant/core/issues/133052) — Dec 2024 S2 regression
- [SoCo issue #557](https://github.com/SoCo/SoCo/issues/557) — ShareLinkPlugin background
- [spotifywebapipython](https://github.com/thlucas1/SpotifyWebApiPython) — Zeroconf + elevated token implementation
- [homeassistantcomponent_spotifyplus](https://github.com/thlucas1/homeassistantcomponent_spotifyplus) — HA component that wraps it
