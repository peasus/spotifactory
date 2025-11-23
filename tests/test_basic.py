from spotifactory import version
from spotifactory.main import greet


def test_version():
    assert isinstance(version, str)


def test_greet():
    assert "Hello" in greet("x")
