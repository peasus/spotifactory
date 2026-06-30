import os
from dataclasses import dataclass
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()

SCOPES = [
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
]


@dataclass
class NowPlayingInfo:
    track_name: str
    artist_name: str
    album_name: str
    album_uri: str
    artwork_url: str


def get_client() -> spotipy.Spotify:
    auth = SpotifyOAuth(
        client_id=os.environ["SPOTIPY_CLIENT_ID"],
        client_secret=os.environ["SPOTIPY_CLIENT_SECRET"],
        redirect_uri=os.environ["SPOTIPY_REDIRECT_URI"],
        scope=" ".join(SCOPES),
    )
    return spotipy.Spotify(auth_manager=auth)


def get_now_playing() -> NowPlayingInfo | None:
    sp = get_client()
    playback = sp.currently_playing()
    if not playback or not playback.get("is_playing") or playback.get("item") is None:
        return None
    item = playback["item"]
    album = item["album"]
    return NowPlayingInfo(
        track_name=item["name"],
        artist_name=", ".join(a["name"] for a in item["artists"]),
        album_name=album["name"],
        album_uri=album["uri"],
        artwork_url=album["images"][0]["url"],
    )
