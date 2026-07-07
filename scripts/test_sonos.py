#!/usr/bin/env python3
"""Test Sonos Spotify playback via SoCo ShareLinkPlugin.

Usage:
    .venv/bin/python scripts/test_sonos.py "Speaker Name"
    .venv/bin/python scripts/test_sonos.py "Speaker Name" spotify:album:4LH4d3cOWNNsVw41Gv4nBa
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

if len(sys.argv) < 2:
    print("Usage: test_sonos.py <speaker_name> [spotify_uri]")
    print("Run list_sonos_speakers.py first to find speaker names.")
    sys.exit(1)

speaker_name = sys.argv[1]
uri = sys.argv[2] if len(sys.argv) > 2 else "spotify:album:4LH4d3cOWNNsVw41Gv4nBa"

print(f"Speaker: {speaker_name!r}")
print(f"URI:     {uri}")
print()

from spotifactory.hardware.sonos import play_spotify_uri

try:
    play_spotify_uri(speaker_name, uri)
    print("OK: playback started")
except RuntimeError as e:
    print(f"FAIL: {e}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
