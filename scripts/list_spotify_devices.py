#!/usr/bin/env python3
"""List all Spotify Connect devices visible to the authenticated account."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from spotifactory.spotify import get_client

sp = get_client()
result = sp.devices()
devices = result.get("devices", [])

if not devices:
    print("No devices found. Make sure Spotify is open/active on at least one device.")
else:
    print(f"{'NAME':<35} {'TYPE':<15} {'ACTIVE':<8} {'ID'}")
    print("-" * 90)
    for d in devices:
        print(f"{d['name']:<35} {d['type']:<15} {str(d['is_active']):<8} {d['id']}")
