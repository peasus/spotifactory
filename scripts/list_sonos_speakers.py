#!/usr/bin/env python3
"""Discover all Sonos speakers on the local network."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import soco
import soco.discovery

print("Scanning for Sonos speakers (up to 10s)...")
speakers = list(soco.discovery.discover(timeout=10) or [])

if not speakers:
    print("No Sonos speakers found.")
else:
    print(f"\n{'NAME':<30} {'IP':<16} {'GROUP'}")
    print("-" * 70)
    for s in sorted(speakers, key=lambda x: x.player_name):
        try:
            group = s.group.label if s.group else "—"
        except Exception:
            group = "?"
        print(f"{s.player_name:<30} {s.ip_address:<16} {group}")
