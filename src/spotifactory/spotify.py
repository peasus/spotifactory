import os
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()

SCOPES = [
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
]


def get_client() -> spotipy.Spotify:
    auth = SpotifyOAuth(
        client_id=os.environ["SPOTIPY_CLIENT_ID"],
        client_secret=os.environ["SPOTIPY_CLIENT_SECRET"],
        redirect_uri=os.environ["SPOTIPY_REDIRECT_URI"],
        scope=" ".join(SCOPES),
    )
    return spotipy.Spotify(auth_manager=auth)
