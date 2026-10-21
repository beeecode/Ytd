"""Thin service layer around yt-dlp."""

import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp

YOUTUBE_HOSTS = {"youtube.com", "youtu.be", "youtube-nocookie.com"}


class InvalidUrlError(ValueError):
    pass


class ExtractionError(RuntimeError):
    @classmethod
    def from_yt_dlp(cls, e: Exception) -> "ExtractionError":
        """Turn a yt-dlp error into a message fit to show users."""
        msg = str(e).removeprefix("ERROR: ")
        # Drop yt-dlp's "please report this issue..." boilerplate.
        msg = msg.split("; please report this issue")[0]
        # Drop the "[youtube] <id>: " prefix.
        msg = re.sub(r"^\[\w+\] [\w-]+: ", "", msg)
        return cls(msg)

    @property
    def transient(self) -> bool:
        # YouTube occasionally returns no formats for a valid video; a retry
        # usually works.
        return "No video formats found" in str(self)


def validate_youtube_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise InvalidUrlError("Please enter a full http(s) URL.")
    host = parsed.hostname.lower()
    if not any(host == h or host.endswith("." + h) for h in YOUTUBE_HOSTS):
        raise InvalidUrlError("Only YouTube URLs are supported.")
    return url


def _simplify_format(f: dict) -> dict:
    has_video = f.get("vcodec") not in (None, "none")
    has_audio = f.get("acodec") not in (None, "none")
    return {
        "format_id": f.get("format_id"),
        "ext": f.get("ext"),
        "height": f.get("height"),
        "fps": f.get("fps"),
        "vcodec": f.get("vcodec") if has_video else None,
        "acodec": f.get("acodec") if has_audio else None,
        "filesize": f.get("filesize") or f.get("filesize_approx"),
        "kind": "av" if has_video and has_audio else "video" if has_video else "audio",
    }


BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noprogress": True,  # progress goes through our hooks, not stdout
    "noplaylist": True,
}


def get_info(url: str) -> dict:
    url = validate_youtube_url(url)
    opts = {**BASE_OPTS, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        # yt-dlp prefixes messages with "ERROR: "; strip it for display.
        raise ExtractionError.from_yt_dlp(e) from e

    formats = [
        _simplify_format(f)
        for f in info.get("formats", [])
        # Skip storyboards and other non-media entries.
        if f.get("vcodec") != "none" or f.get("acodec") != "none"
        if f.get("format_note") != "storyboard" and f.get("ext") != "mhtml"
    ]
    heights = sorted(
        {f["height"] for f in formats if f["kind"] != "audio" and f["height"]},
        reverse=True,
    )

    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "webpage_url": info.get("webpage_url"),
        "video_qualities": heights,
        "formats": formats,
    }


def _format_sort(quality: int | None) -> list[str]:
    # Highest resolution up to the cap first, then H.264/AAC at that
    # resolution for player compatibility (AV1/VP9 only where YouTube has
    # nothing else, e.g. 1440p+).
    res = f"res:{quality}" if quality else "res"
    return [res, "vcodec:h264", "acodec:aac"]


def download(
    url: str,
    out_dir: Path,
    *,
    kind: str,
    quality: int | None,
    audio_format: str,
    max_duration: int,
    max_filesize: int,
    on_progress: Callable[[dict], None],
) -> Path:
    """Download into out_dir and return the path of the finished file."""
    url = validate_youtube_url(url)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Video jobs download two streams (video, then audio); report one overall
    # percentage across both instead of 0-100% twice.
    parts = {"count": 1, "seen": []}

    def progress_hook(d: dict) -> None:
        if d["status"] == "downloading":
            if d.get("filename") not in parts["seen"]:
                parts["seen"].append(d.get("filename"))
            index = len(parts["seen"]) - 1
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            percent = None
            if total:
                percent = round((index + done / total) / parts["count"] * 100, 1)
            on_progress({
                "stage": "downloading",
                "percent": min(percent, 100.0) if percent is not None else None,
                "downloaded_bytes": done,
                "total_bytes": total,
                "speed": d.get("speed"),
                "eta": d.get("eta"),
            })

    def postprocessor_hook(d: dict) -> None:
        if d["status"] == "started":
            on_progress({"stage": "processing", "percent": None})

    opts = {
        **BASE_OPTS,
        "format": "bestaudio/best" if kind == "audio" else "bestvideo*+bestaudio/best",
        "outtmpl": str(out_dir / "%(title).150B [%(id)s].%(ext)s"),
        "windowsfilenames": True,
        "max_filesize": max_filesize,
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],
    }
    if kind == "audio":
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": audio_format,
            "preferredquality": "192",
        }]
    else:
        opts["format_sort"] = _format_sort(quality)
        opts["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            duration = info.get("duration") or 0
            if duration > max_duration:
                raise ExtractionError(
                    f"Video is too long ({duration // 60} min). "
                    f"Limit is {max_duration // 60} min."
                )
            if info.get("is_live"):
                raise ExtractionError("Live streams can't be downloaded.")
            parts["count"] = max(len(info.get("requested_formats") or []), 1)
            ydl.process_ie_result(info, download=True)
    except yt_dlp.utils.DownloadError as e:
        raise ExtractionError.from_yt_dlp(e) from e

    files = [p for p in out_dir.iterdir() if p.is_file() and not p.name.endswith(".part")]
    if not files:
        # yt-dlp silently skips files over max_filesize.
        raise ExtractionError(
            f"File is larger than the {max_filesize // 1024**2} MB limit."
        )
    return max(files, key=lambda p: p.stat().st_size)
