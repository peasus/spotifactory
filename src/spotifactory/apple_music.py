"""Apple Music links for Spotify albums, so a tag can carry both and play on a
box whose speaker plays Apple Music (Sonos) later on.

Uses Apple's public iTunes Search API (no account). The match must be sure:
same artist, same album name (ignoring "(Live)", "[Remastered]" and the like)
and the same number of tracks, because a barcode alone often lands on a
deluxe or anniversary reissue. No sure match, no link.
"""
from __future__ import annotations

import re

import requests

_SEARCH = "https://itunes.apple.com/search"
_LOOKUP = "https://itunes.apple.com/lookup"
_TIMEOUT = 5


def _norm(name: str) -> str:
    """'MTV Unplugged In New York (Live Acoustic)' -> 'mtv unplugged in new york'."""
    name = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", name)      # (Live), [Remastered]
    name = re.sub(r"\s+-\s+.*$", " ", name)                 # " - 2011 Remaster"
    name = re.sub(r"[^\w\s]", " ", name.casefold())
    return " ".join(name.split())


def _fits(candidate: dict, artist: str, album: str, tracks: int) -> bool:
    return (candidate.get("wrapperType") == "collection"
            and candidate.get("trackCount") == tracks
            and _norm(candidate.get("collectionName", "")) == _norm(album)
            and _norm(artist) in _norm(candidate.get("artistName", "")))


def album_link(artist: str, album: str, tracks: int, upc: str | None = None) -> str | None:
    """The Apple Music link for this album, or None if there's no sure match."""
    try:
        found = requests.get(_SEARCH, params={"term": f"{artist} {album}", "entity": "album",
                                              "limit": 25}, timeout=_TIMEOUT).json()
        candidates = found.get("results", [])
        if upc:
            by_upc = requests.get(_LOOKUP, params={"upc": upc, "entity": "album"},
                                  timeout=_TIMEOUT).json()
            candidates += by_upc.get("results", [])
    except Exception as e:
        print(f"[apple] lookup failed: {e}", flush=True)
        return None
    for c in candidates:
        if _fits(c, artist, album, tracks):
            return f"https://music.apple.com/album/{c['collectionId']}"
    return None


def link_for_spotify_album(album_uri: str) -> str | None:
    """Look up a Spotify album, then its Apple Music twin. None if either fails."""
    try:
        from spotifactory.spotify import get_client
        a = get_client().album(album_uri.split(":")[-1])
    except Exception as e:
        print(f"[apple] spotify album lookup failed: {e}", flush=True)
        return None
    artist = (a.get("artists") or [{}])[0].get("name", "")
    upc = (a.get("external_ids") or {}).get("upc")
    link = album_link(artist, a.get("name", ""), a.get("total_tracks") or 0, upc)
    print(f"[apple] {artist} - {a.get('name')}: {link or 'no sure match, Spotify only'}", flush=True)
    return link
