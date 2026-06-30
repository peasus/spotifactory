from io import BytesIO

import requests

from spotifactory.spotify import get_now_playing, NowPlayingInfo
from spotifactory.printer import print_image
from spotifactory.rfid import write_uri


class CaptureJob:
    """Fetches album art for the current Spotify track, prints it, and writes
    the album URI to an RFID tag — all in sequence."""

    def run(self) -> NowPlayingInfo | None:
        info = get_now_playing()
        if info is None:
            print("Nothing is currently playing.")
            return None

        print(f"Now playing: {info.track_name} — {info.artist_name} ({info.album_name})")

        image = self._download_artwork(info.artwork_url)

        print("Printing artwork...")
        print_image(image)

        print("Scan an RFID tag to write the album URI...")
        write_uri(info.album_uri)
        print(f"Written: {info.album_uri}")

        return info

    def _download_artwork(self, url: str) -> BytesIO:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return BytesIO(response.content)


if __name__ == "__main__":
    CaptureJob().run()
