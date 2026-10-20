"""Settings, read from environment variables."""

import os
from pathlib import Path


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", "downloads")).resolve()
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")

# Abuse limits for a public deployment.
MAX_DURATION_SECONDS = _int("MAX_DURATION_SECONDS", 2 * 60 * 60)
MAX_FILESIZE_BYTES = _int("MAX_FILESIZE_BYTES", 2 * 1024**3)
JOB_TIMEOUT_SECONDS = _int("JOB_TIMEOUT_SECONDS", 30 * 60)
JOBS_PER_HOUR_PER_IP = _int("JOBS_PER_HOUR_PER_IP", 20)
INFO_PER_MINUTE_PER_IP = _int("INFO_PER_MINUTE_PER_IP", 30)
MAX_QUEUE_LENGTH = _int("MAX_QUEUE_LENGTH", 100)

# Finished files and job records are removed after this long.
FILE_TTL_SECONDS = _int("FILE_TTL_SECONDS", 60 * 60)
