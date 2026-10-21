"""Jobs executed by the RQ worker."""

import time

from rq import get_current_job

from . import config, ytdl

# Minimum seconds between progress writes to Redis.
PROGRESS_INTERVAL = 0.5
# Retries for transient YouTube errors.
ATTEMPTS = 2
RETRY_DELAY = 3


def download_job(url: str, kind: str, quality: int | None, audio_format: str) -> dict:
    job = get_current_job()
    last_write = 0.0

    def on_progress(progress: dict) -> None:
        nonlocal last_write
        now = time.monotonic()
        # Always write stage changes; throttle plain percentage updates.
        stage_changed = job.meta.get("progress", {}).get("stage") != progress["stage"]
        if stage_changed or now - last_write >= PROGRESS_INTERVAL:
            job.meta["progress"] = progress
            job.save_meta()
            last_write = now

    for attempt in range(1, ATTEMPTS + 1):
        try:
            path = ytdl.download(
                url,
                config.DOWNLOAD_DIR / job.id,
                kind=kind,
                quality=quality,
                audio_format=audio_format,
                max_duration=config.MAX_DURATION_SECONDS,
                max_filesize=config.MAX_FILESIZE_BYTES,
                on_progress=on_progress,
            )
            break
        except ytdl.ExtractionError as e:
            if e.transient and attempt < ATTEMPTS:
                time.sleep(RETRY_DELAY)
                continue
            # User-facing message; the API reads it from meta.
            job.meta["error"] = str(e)
            job.save_meta()
            raise

    return {"filename": path.name, "filesize": path.stat().st_size}
