# Ytd

YouTube downloader web app. FastAPI + yt-dlp backend with a Redis/RQ job queue, Next.js frontend.

```
Browser ──► FastAPI (api) ──► Redis queue ──► RQ worker(s): yt-dlp + ffmpeg
   ▲             │                                   │
   └── SSE progress / file download ◄── shared downloads volume
```

## Run with Docker (recommended)

```powershell
copy .env.example .env      # adjust limits if needed
docker compose up -d --build
docker compose up -d --scale worker=4   # more parallel downloads
```

API: http://localhost:8000 — interactive docs at http://localhost:8000/docs

## Run locally without Docker

Needs Python 3.12+, ffmpeg and [Deno](https://deno.com) on `PATH`, and Redis
(`docker compose up -d redis` is the easiest way to get it).

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt

# terminal 1
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
# terminal 2
.\.venv\Scripts\python -m app.worker
```

## Frontend

```powershell
cd frontend
npm install
npm run dev        # http://localhost:3000
```

The UI calls same-origin `/api/*`. In development, Next.js proxies those
requests to `API_URL` (default `http://localhost:8000`) — see
[next.config.ts](frontend/next.config.ts).

## API

| Method | Endpoint                 | Purpose                                          |
|--------|--------------------------|--------------------------------------------------|
| GET    | `/api/health`            | Health check + queue length                      |
| POST   | `/api/info`              | `{"url"}` → title, thumbnail, qualities, formats |
| POST   | `/api/jobs`              | `{"url", "kind": "video"\|"audio", "quality": 1080, "audio_format": "mp3"\|"m4a"}` → job |
| GET    | `/api/jobs/{id}`         | Job status, progress, queue position             |
| GET    | `/api/jobs/{id}/events`  | Live job updates (Server-Sent Events)            |
| GET    | `/api/files/{id}`        | Download the finished file                       |

## Configuration

All settings are environment variables — see [.env.example](.env.example).
Public-facing limits: per-IP rate limits, max video duration, max file size,
job timeout, and max queue length. Finished files are deleted after
`FILE_TTL_SECONDS`.

## Deploying publicly — notes

- **Put it behind a reverse proxy** (Caddy/nginx) with HTTPS. Set uvicorn's
  `FORWARDED_ALLOW_IPS` to the proxy's IP so rate limits see real client IPs.
  Don't set it to `*` while the API is directly exposed, or clients can spoof IPs.
- **YouTube blocks datacenter IPs.** Expect "Sign in to confirm you're not a bot"
  errors from cloud servers. Keep yt-dlp updated; you may need cookies or a proxy.
- **Keep yt-dlp updated** — rebuild the image regularly (`docker compose build --pull`).
- **Legal:** downloading violates YouTube's Terms of Service, and public
  downloaders can receive DMCA notices. Add terms of use telling users to only
  download content they have rights to, and have a takedown contact.
