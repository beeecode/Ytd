"""Unit tests for the yt-dlp service layer (yt-dlp itself is faked)."""

from pathlib import Path

import pytest
import yt_dlp

from app import ytdl


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    "https://youtube.com/watch?v=jNQXAC9IVRw",
    "https://m.youtube.com/watch?v=jNQXAC9IVRw",
    "https://music.youtube.com/watch?v=jNQXAC9IVRw",
    "https://youtu.be/jNQXAC9IVRw",
    "https://www.youtube.com/shorts/abc123",
    "  https://youtu.be/jNQXAC9IVRw  ",
])
def test_valid_urls(url):
    assert ytdl.validate_youtube_url(url) == url.strip()


@pytest.mark.parametrize("url", [
    "not a url",
    "youtube.com/watch?v=x",             # no scheme
    "ftp://youtube.com/x",
    "https://vimeo.com/123",
    "https://notyoutube.com/watch?v=x",  # suffix match must be on a dot boundary
    "https://youtube.com.evil.com/x",
    "file:///etc/passwd",
])
def test_invalid_urls(url):
    with pytest.raises(ytdl.InvalidUrlError):
        ytdl.validate_youtube_url(url)


def test_error_message_cleanup():
    raw = (
        "ERROR: [youtube] jNQXAC9IVRw: No video formats found!; please report this issue on "
        " https://github.com/yt-dlp/yt-dlp/issues?q= , filling out the appropriate issue template."
    )
    e = ytdl.ExtractionError.from_yt_dlp(Exception(raw))
    assert str(e) == "No video formats found!"
    assert e.transient

    e = ytdl.ExtractionError.from_yt_dlp(Exception("ERROR: [youtube] xxxxxxxxxxx: This video is unavailable"))
    assert str(e) == "This video is unavailable"
    assert not e.transient


def test_format_sort_prefers_h264_within_resolution_cap():
    assert ytdl._format_sort(720) == ["res:720", "vcodec:h264", "acodec:aac"]
    assert ytdl._format_sort(None)[0] == "res"


class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL; behaviour is set per test via class attrs."""

    info: dict = {}
    parts: list[str] = []  # filenames "downloaded", one per stream
    write_file = True
    error: str | None = None
    last_opts: dict = {}

    def __init__(self, opts):
        self.opts = opts
        FakeYDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download):
        if self.error:
            raise yt_dlp.utils.DownloadError(self.error)
        return self.info

    def process_ie_result(self, info, download):
        for name in self.parts:
            for done in (50, 100):
                for hook in self.opts["progress_hooks"]:
                    hook({"status": "downloading", "filename": name,
                          "downloaded_bytes": done, "total_bytes": 100})
        for hook in self.opts["postprocessor_hooks"]:
            hook({"status": "started"})
        if self.write_file:
            (Path(self.opts["outtmpl"]).parent / "My Video [abc].mp4").write_bytes(b"data")


@pytest.fixture
def fake_ydl(monkeypatch):
    FakeYDL.info = {"duration": 60, "requested_formats": [{}, {}]}
    FakeYDL.parts = ["v.f137.mp4", "a.f140.m4a"]
    FakeYDL.write_file = True
    FakeYDL.error = None
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    return FakeYDL


def run_download(tmp_path, **overrides):
    events = []
    kwargs = dict(kind="video", quality=720, audio_format="mp3",
                  max_duration=3600, max_filesize=10**9, on_progress=events.append)
    kwargs.update(overrides)
    path = ytdl.download("https://youtu.be/abc", tmp_path / "job", **kwargs)
    return path, events


def test_download_reports_one_overall_percentage_across_streams(tmp_path, fake_ydl):
    path, events = run_download(tmp_path)
    assert path.name == "My Video [abc].mp4"
    percents = [e["percent"] for e in events if e["stage"] == "downloading"]
    # Two streams, each 50% then 100%, mapped onto a single 0-100 scale.
    assert percents == [25.0, 50.0, 75.0, 100.0]
    assert events[-1]["stage"] == "processing"


def test_download_single_stream(tmp_path, fake_ydl):
    fake_ydl.info = {"duration": 60}  # no requested_formats: one stream
    fake_ydl.parts = ["a.webm"]
    _, events = run_download(tmp_path, kind="audio")
    assert [e["percent"] for e in events if e["stage"] == "downloading"] == [50.0, 100.0]


def test_download_video_options(tmp_path, fake_ydl):
    run_download(tmp_path, quality=1080)
    opts = fake_ydl.last_opts
    assert opts["format_sort"][0] == "res:1080"
    assert opts["merge_output_format"] == "mp4"
    assert opts["noplaylist"] is True
    assert "postprocessors" not in opts


def test_download_audio_options(tmp_path, fake_ydl):
    run_download(tmp_path, kind="audio", audio_format="m4a")
    opts = fake_ydl.last_opts
    assert opts["format"] == "bestaudio/best"
    assert opts["postprocessors"][0]["preferredcodec"] == "m4a"
    assert "merge_output_format" not in opts


def test_download_rejects_long_videos(tmp_path, fake_ydl):
    fake_ydl.info = {"duration": 7201}
    with pytest.raises(ytdl.ExtractionError, match="too long"):
        run_download(tmp_path, max_duration=7200)


def test_download_rejects_live_streams(tmp_path, fake_ydl):
    fake_ydl.info = {"duration": 0, "is_live": True}
    with pytest.raises(ytdl.ExtractionError, match="Live"):
        run_download(tmp_path)


def test_download_reports_oversized_file(tmp_path, fake_ydl):
    # yt-dlp skips files over max_filesize silently, leaving nothing behind.
    fake_ydl.write_file = False
    with pytest.raises(ytdl.ExtractionError, match="larger than"):
        run_download(tmp_path)


def test_download_wraps_yt_dlp_errors(tmp_path, fake_ydl):
    fake_ydl.error = "ERROR: [youtube] abc: Private video"
    with pytest.raises(ytdl.ExtractionError, match="^Private video$"):
        run_download(tmp_path)


@pytest.mark.network
def test_get_info_real_youtube():
    info = ytdl.get_info("https://www.youtube.com/watch?v=jNQXAC9IVRw")
    assert info["title"] == "Me at the zoo"
    assert info["video_qualities"]
