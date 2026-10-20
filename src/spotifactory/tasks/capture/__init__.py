from spotifactory.tasks.base import Task
from spotifactory.tasks.capture.steps import (
    ConfirmStep,
    DoneStep,
    FetchArtStep,
    FetchInfoStep,
    FetchPlaylistArtStep,
    FetchPlaylistInfoStep,
    PlaylistConfirmStep,
    PlaylistDoneStep,
    PlaylistLabelStep,
    PlaylistScanStep,
    PrintStep,
    ScanStep,
)


class CaptureTask(Task):
    name = "capture"
    steps = [
        ("fetch_info", FetchInfoStep),
        ("confirm",    ConfirmStep),
        ("fetch_art",  FetchArtStep),
        ("print",      PrintStep),
        ("scan",       ScanStep),
        ("done",       DoneStep),
    ]


class CapturePlaylistTask(Task):
    name = "capture_playlist"
    steps = [
        ("fetch_info", FetchPlaylistInfoStep),
        ("confirm",    PlaylistConfirmStep),
        ("label",      PlaylistLabelStep),
        ("fetch_art",  FetchPlaylistArtStep),
        ("print",      PrintStep),
        ("scan",       PlaylistScanStep),
        ("done",       PlaylistDoneStep),
    ]
