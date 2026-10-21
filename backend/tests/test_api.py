"""API tests: fake Redis, jobs run synchronously, yt-dlp faked."""

import json
import os
import time

from app import config, main, ytdl

URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok", "queued": 0, "workers": 1}


def test_info(client, monkeypatch):
    monkeypatch.setattr("app.ytdl.get_info", lambda url: {"title": "Me at the zoo"})
    r = client.post("/api/info", json={"url": URL})
    assert r.status_code == 200
    assert r.json()["title"] == "Me at the zoo"


def test_info_invalid_url(client):
    r = client.post("/api/info", json={"url": "https://vimeo.com/1"})
    assert r.status_code == 400
    assert r.json()["detail"] == "Only YouTube URLs are supported."


def test_info_extraction_error(client, monkeypatch):
    def fail(url):
        raise ytdl.ExtractionError("This video is unavailable")

    monkeypatch.setattr("app.ytdl.get_info", fail)
    r = client.post("/api/info", json={"url": URL})
    assert r.status_code == 422
    assert r.json()["detail"] == "This video is unavailable"


def test_video_job_end_to_end(client, fake_download):
    r = client.post("/api/jobs", json={"url": URL, "kind": "video", "quality": 720})
    assert r.status_code == 202
    job = r.json()
    assert job["status"] == "finished"
    assert job["file"]["filename"] == "video.mp4"
    assert job["file"]["filesize"] == 1234
    assert fake_download[0]["quality"] == 720

    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "finished"

    f = client.get(job["file"]["url"])
    assert f.status_code == 200
    assert f.content == b"x" * 1234
    assert "video.mp4" in f.headers["content-disposition"]


def test_audio_job(client, fake_download):
    job = client.post("/api/jobs", json={"url": URL, "kind": "audio", "audio_format": "m4a"}).json()
    assert job["file"]["filename"] == "song.mp3"
    assert fake_download[0]["kind"] == "audio"
    assert fake_download[0]["audio_format"] == "m4a"


def test_job_validation(client):
    assert client.post("/api/jobs", json={"url": "https://example.com"}).status_code == 400
    assert client.post("/api/jobs", json={"url": URL, "kind": "gif"}).status_code == 422
    assert client.post("/api/jobs", json={"url": URL, "quality": 99999}).status_code == 422


def test_failed_job_exposes_friendly_error(client, monkeypatch):
    def fail(*args, **kwargs):
        raise ytdl.ExtractionError("This video is unavailable")

    monkeypatch.setattr("app.ytdl.download", fail)
    job = client.post("/api/jobs", json={"url": URL}).json()
    assert job["status"] == "failed"
    assert job["error"] == "This video is unavailable"
    assert client.get(f"/api/files/{job['id']}").status_code == 409


def test_unexpected_failure_has_generic_error(client, monkeypatch):
    def crash(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.ytdl.download", crash)
    job = client.post("/api/jobs", json={"url": URL}).json()
    assert job["status"] == "failed"
    assert job["error"] == "Download failed."  # internals not leaked


def test_transient_error_is_retried(client, monkeypatch, fake_download):
    monkeypatch.setattr("app.tasks.RETRY_DELAY", 0)
    real = ytdl.download
    attempts = []

    def flaky(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise ytdl.ExtractionError("No video formats found!")
        return real(*args, **kwargs)

    monkeypatch.setattr("app.ytdl.download", flaky)
    job = client.post("/api/jobs", json={"url": URL}).json()
    assert job["status"] == "finished"
    assert len(attempts) == 2


def test_unknown_and_malformed_job_ids(client):
    assert client.get("/api/jobs/00000000-0000-0000-0000-000000000000").status_code == 404
    assert client.get("/api/jobs/not-a-uuid").status_code == 404
    assert client.get("/api/files/..%2F..%2Fetc").status_code == 404


def test_expired_file_returns_410(client, fake_download):
    job = client.post("/api/jobs", json={"url": URL}).json()
    (config.DOWNLOAD_DIR / job["id"] / "video.mp4").unlink()
    assert client.get(job["file"]["url"]).status_code == 410


def test_events_stream(client, fake_download):
    job = client.post("/api/jobs", json={"url": URL}).json()
    with client.stream("GET", f"/api/jobs/{job['id']}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        lines = [line for line in r.iter_lines() if line.startswith("data: ")]
    # Job is already finished, so exactly one event and the stream closes.
    assert len(lines) == 1
    assert json.loads(lines[0][6:])["status"] == "finished"


def test_job_rate_limit(client, fake_download, monkeypatch):
    monkeypatch.setattr(config, "JOBS_PER_HOUR_PER_IP", 2)
    codes = [client.post("/api/jobs", json={"url": URL}).status_code for _ in range(3)]
    assert codes == [202, 202, 429]


def test_info_rate_limit(client, monkeypatch):
    monkeypatch.setattr(config, "INFO_PER_MINUTE_PER_IP", 1)
    monkeypatch.setattr("app.ytdl.get_info", lambda url: {})
    codes = [client.post("/api/info", json={"url": URL}).status_code for _ in range(2)]
    assert codes == [200, 429]


def test_rate_limit_resets_in_new_window(client, fake_download, monkeypatch):
    monkeypatch.setattr(config, "JOBS_PER_HOUR_PER_IP", 1)
    now = time.time()
    monkeypatch.setattr(main.time, "time", lambda: now)
    assert client.post("/api/jobs", json={"url": URL}).status_code == 202
    assert client.post("/api/jobs", json={"url": URL}).status_code == 429
    monkeypatch.setattr(main.time, "time", lambda: now + 3600)
    assert client.post("/api/jobs", json={"url": URL}).status_code == 202


def test_queue_full(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_QUEUE_LENGTH", 0)
    r = client.post("/api/jobs", json={"url": URL})
    assert r.status_code == 503


def test_no_workers_rejects_job_instead_of_queueing_forever(client, monkeypatch):
    monkeypatch.setattr(main, "worker_count", lambda: 0)
    r = client.post("/api/jobs", json={"url": URL})
    assert r.status_code == 503
    assert "unavailable" in r.json()["detail"]
    assert len(main.download_queue) == 0


def test_worker_count_sees_registered_workers(redis, monkeypatch):
    from rq import Queue, Worker

    queue = Queue("downloads", connection=redis)
    monkeypatch.setattr(main, "redis_conn", redis)
    monkeypatch.setattr(main, "download_queue", queue)
    assert main.worker_count() == 0
    worker = Worker([queue], connection=redis)
    worker.register_birth()
    assert main.worker_count() == 1
    worker.register_death()
    assert main.worker_count() == 0


def test_default_download_dir_is_independent_of_cwd():
    from pathlib import Path

    import app

    if "DOWNLOAD_DIR" not in os.environ:
        assert config.DOWNLOAD_DIR == Path(app.__file__).resolve().parent.parent / "downloads"


def test_cleanup_removes_only_old_job_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr(config, "FILE_TTL_SECONDS", 3600)
    old, new = tmp_path / "old-job", tmp_path / "new-job"
    old.mkdir()
    new.mkdir()
    two_hours_ago = time.time() - 7200
    os.utime(old, (two_hours_ago, two_hours_ago))

    main.cleanup_downloads()

    assert not old.exists()
    assert new.exists()
