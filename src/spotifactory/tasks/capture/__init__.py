from spotifactory.tasks.base import Task
from spotifactory.tasks.capture.steps import (
    AlbumLabelStep,
    ChooseTagTargetStep,
    TagWrittenStep,
    WriteChosenTagStep,
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
        ("label",      AlbumLabelStep),
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


class WriteTagTask(Task):
    """Menu > Write Tag: put what's playing on a tag, without printing."""
    name = "write_tag"
    steps = [
        ("choose", ChooseTagTargetStep),
        ("write",  WriteChosenTagStep),
        ("done",   TagWrittenStep),
    ]
