import asyncio
import json
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from rq.exceptions import NoSuchJobError
from rq.job import Job, JobStatus
from rq.worker import Worker

from . import config, tasks, ytdl
from .broker import download_queue, redis_conn

TERMINAL_STATUSES = {s.value for s in (JobStatus.FINISHED, JobStatus.FAILED, JobStatus.STOPPED, JobStatus.CANCELED)}
CLEANUP_INTERVAL_SECONDS = 5 * 60


def cleanup_downloads() -> None:
    """Delete job folders older than FILE_TTL_SECONDS."""
    if not config.DOWNLOAD_DIR.exists():
        return
    cutoff = time.time() - config.FILE_TTL_SECONDS
    for path in config.DOWNLOAD_DIR.iterdir():
        if path.is_dir() and path.stat().st_mtime < cutoff:
            shutil.rmtree(path, ignore_errors=True)


async def cleanup_loop() -> None:
    while True:
        await asyncio.to_thread(cleanup_downloads)
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(cleanup_loop())
    yield
    task.cancel()


app = FastAPI(title="Ytd", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class InfoRequest(BaseModel):
    url: str


class JobRequest(BaseModel):
    url: str
    kind: Literal["video", "audio"] = "video"
    quality: int | None = Field(None, ge=144, le=4320, description="Max video height")
    audio_format: Literal["mp3", "m4a"] = "mp3"


def rate_limit(request: Request, bucket: str, limit: int, window: int) -> None:
    """Fixed-window per-IP limit backed by Redis."""
    ip = request.client.host if request.client else "unknown"
    key = f"ratelimit:{bucket}:{ip}:{int(time.time() // window)}"
    pipe = redis_conn.pipeline()
    pipe.incr(key)
    pipe.expire(key, window)
    count, _ = pipe.execute()
    if count > limit:
        raise HTTPException(status_code=429, detail="Too many requests. Please slow down.")


def worker_count() -> int:
    return Worker.count(connection=redis_conn, queue=download_queue)


def fetch_job(job_id: str) -> Job:
    try:
        uuid.UUID(job_id)
        return Job.fetch(job_id, connection=redis_conn)
    except (ValueError, NoSuchJobError):
        raise HTTPException(status_code=404, detail="Job not found or expired.")


def job_state(job: Job) -> dict:
    status = job.get_status()
    status = status.value if status else None
    state = {
        "id": job.id,
        "status": status,
        "progress": job.meta.get("progress"),
    }
    if status == JobStatus.QUEUED.value:
        state["position"] = job.get_position()
    elif status == JobStatus.FINISHED.value:
        result = job.return_value() or {}
        state["file"] = {**result, "url": f"/api/files/{job.id}"}
    elif status in TERMINAL_STATUSES:
        state["error"] = job.meta.get("error", "Download failed.")
    return state


@app.get("/api/health")
def health():
    redis_conn.ping()
    return {"status": "ok", "queued": len(download_queue), "workers": worker_count()}


# Sync handlers run in FastAPI's threadpool, so blocking yt-dlp/Redis calls
# don't stall the event loop.
@app.post("/api/info")
def info(req: InfoRequest, request: Request):
    rate_limit(request, "info", config.INFO_PER_MINUTE_PER_IP, 60)
    try:
        return ytdl.get_info(req.url)
    except ytdl.InvalidUrlError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ytdl.ExtractionError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/api/jobs", status_code=202)
def create_job(req: JobRequest, request: Request):
    try:
        url = ytdl.validate_youtube_url(req.url)
    except ytdl.InvalidUrlError as e:
        raise HTTPException(status_code=400, detail=str(e))
    rate_limit(request, "jobs", config.JOBS_PER_HOUR_PER_IP, 3600)
    if len(download_queue) >= config.MAX_QUEUE_LENGTH:
        raise HTTPException(status_code=503, detail="Server is busy. Try again shortly.")
    if worker_count() == 0:
        # Otherwise the job would sit in the queue forever.
        raise HTTPException(status_code=503, detail="Downloads are temporarily unavailable. Try again shortly.")

    job = download_queue.enqueue(
        tasks.download_job,
        url,
        req.kind,
        req.quality,
        req.audio_format,
        job_timeout=config.JOB_TIMEOUT_SECONDS,
        result_ttl=config.FILE_TTL_SECONDS,
        failure_ttl=config.FILE_TTL_SECONDS,
    )
    return job_state(job)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return job_state(fetch_job(job_id))


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request):
    """Server-Sent Events stream of job state until it finishes."""
    await asyncio.to_thread(fetch_job, job_id)  # 404 before opening the stream

    async def stream():
        last_payload, last_sent = None, time.monotonic()
        while not await request.is_disconnected():
            try:
                job = await asyncio.to_thread(fetch_job, job_id)
                state = await asyncio.to_thread(job_state, job)
            except HTTPException:
                yield f"event: error\ndata: {json.dumps({'error': 'Job expired.'})}\n\n"
                return
            payload = json.dumps(state)
            if payload != last_payload:
                yield f"data: {payload}\n\n"
                last_payload, last_sent = payload, time.monotonic()
            elif time.monotonic() - last_sent > 15:
                yield ": keep-alive\n\n"  # stops proxies closing idle streams
                last_sent = time.monotonic()
            if state["status"] in TERMINAL_STATUSES:
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/files/{job_id}")
def get_file(job_id: str):
    job = fetch_job(job_id)
    if job.get_status() != JobStatus.FINISHED:
        raise HTTPException(status_code=409, detail="File is not ready yet.")
    filename = (job.return_value() or {}).get("filename")
    job_dir = (config.DOWNLOAD_DIR / job.id).resolve()
    path = (job_dir / filename).resolve() if filename else None
    if not path or path.parent != job_dir or not path.is_file():
        raise HTTPException(status_code=410, detail="File has expired.")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")
