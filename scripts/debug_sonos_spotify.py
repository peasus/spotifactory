#!/usr/bin/env python3
"""Diagnose Sonos Spotify music service configuration."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import soco, soco.discovery
from soco.music_services import MusicService
from soco.plugins.sharelink import ShareLinkPlugin, SpotifyShare

# Find coordinator
speakers = list(soco.discovery.discover(timeout=10) or [])
coordinator = next(
    (s.group.coordinator for s in speakers if s.player_name == "Kitchen"),
    None
)
if not coordinator:
    print("Kitchen not found"); sys.exit(1)

print(f"Coordinator: {coordinator.player_name} ({coordinator.ip_address})")
print()

# Check if Spotify music service exists on this system
print("==> Music services on this Sonos:")
try:
    for ms in MusicService.get_all_music_services_names():
        if "spot" in ms.lower():
            print(f"  FOUND: {ms!r}")
except Exception as e:
    print(f"  Error listing services: {e}")

print()
print("==> Attempting to add a single track (simpler than album):")
TRACK_URI = "spotify:track:3n3Ppam7vgaVa1iaRUIOKE"  # "Mr. Brightside"
try:
    from spotifactory.hardware.sonos import _ensure_spotify_service_number
    _ensure_spotify_service_number()
    plugin = ShareLinkPlugin(coordinator)
    pos = plugin.add_share_link_to_queue(TRACK_URI)
    print(f"  OK: added at queue position {pos}")
    coordinator.play_from_queue(pos - 1)
    print(f"  OK: playing")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")

print()
print("==> Attempting with open.spotify.com URL format:")
ALBUM_URL = "https://open.spotify.com/album/4LH4d3cOWNNsVw41Gv4nBa"
try:
    from spotifactory.hardware.sonos import _ensure_spotify_service_number
    _ensure_spotify_service_number()
    plugin = ShareLinkPlugin(coordinator)
    pos = plugin.add_share_link_to_queue(ALBUM_URL)
    print(f"  OK: added at queue position {pos}")
except Exception as e:
    print(f"  Error: {type(e).__name__}: {e}")
