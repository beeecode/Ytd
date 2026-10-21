import fakeredis
import pytest
from fastapi.testclient import TestClient
from rq import Queue

from app import config, main


def pytest_addoption(parser):
    parser.addoption("--network", action="store_true", help="run tests that hit real YouTube")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--network"):
        return
    skip = pytest.mark.skip(reason="needs --network")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def redis():
    return fakeredis.FakeStrictRedis()


@pytest.fixture
def client(redis, tmp_path, monkeypatch):
    """API client backed by fake Redis; jobs run synchronously on enqueue."""
    monkeypatch.setattr(main, "redis_conn", redis)
    monkeypatch.setattr(main, "download_queue", Queue("downloads", connection=redis, is_async=False))
    monkeypatch.setattr(config, "DOWNLOAD_DIR", tmp_path)
    # Sync mode has no real worker process; pretend one is running.
    monkeypatch.setattr(main, "worker_count", lambda: 1)
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def fake_download(monkeypatch):
    """Replace the real yt-dlp download with one that writes a small file."""
    calls = []

    def download(url, out_dir, *, kind, on_progress, **kwargs):
        calls.append({"url": url, "kind": kind, **kwargs})
        on_progress({"stage": "downloading", "percent": 50.0})
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / ("song.mp3" if kind == "audio" else "video.mp4")
        path.write_bytes(b"x" * 1234)
        return path

    monkeypatch.setattr("app.ytdl.download", download)
    return calls
