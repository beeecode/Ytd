# Ytd

YouTube downloader web app. FastAPI + yt-dlp backend with a Redis/RQ job queue, Next.js frontend.

```
                ┌─ /api/* ──► FastAPI (api) ──► Redis queue ──► RQ worker(s): yt-dlp + ffmpeg
Browser ─► Caddy┤                  ▲                                  │
   (HTTPS)      └─ /*  ──► Next.js (frontend)      └── shared downloads volume ◄──┘
```

## Run with Docker (recommended)

```powershell
copy .env.example .env      # set DOMAIN, adjust limits if needed
docker compose up -d --build
docker compose up -d --scale worker=4   # more parallel downloads
```

Open https://localhost (Caddy uses a self-signed local certificate for
`localhost`, so the browser will warn once).

## Run locally without Docker

Needs Python 3.12+, ffmpeg and [Deno](https://deno.com) on `PATH`, and Redis
(`docker compose up -d redis` is the easiest way to get it).

Always run **both** the API and a worker locally. Local processes use Redis
DB 1 and the Docker stack uses DB 0, so a local API never hands jobs to Docker
workers. They don't share a downloads folder, so a file saved by a Docker
worker would be invisible to a local API (you'd get "File has expired").
Without a worker running, the API answers `503 Downloads are temporarily unavailable`.

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

## Tests

```powershell
cd backend
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest            # fast, offline (fake Redis + fake yt-dlp)
.\.venv\Scripts\python -m pytest --network  # also hits real YouTube
```

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs the backend tests,
frontend lint/typecheck/build, and the Docker build on every push and PR.

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

## Deploying to a server

1. Get a Linux VPS with Docker installed and point your domain's DNS
   (A/AAAA record) at it.
2. Open ports 80 and 443 in the firewall. Nothing else needs to be public.
3. Clone the repo, then `cp .env.example .env` and set `DOMAIN=yourdomain.com`.
4. `docker compose up -d --build`. Caddy gets a Let's Encrypt certificate automatically.

Updating: `git pull && docker compose up -d --build`. Rebuild with
`docker compose build --pull --no-cache api worker` regularly to pick up new
yt-dlp releases.

Logs: `docker compose logs -f caddy api worker`.

### Notes

- **Real client IPs:** Caddy overwrites `X-Forwarded-For` with the visitor's IP
  and the API trusts it (`FORWARDED_ALLOW_IPS`). The API port isn't published,
  so it can only be reached through Caddy. If you put Cloudflare in front,
  add Cloudflare's ranges as `trusted_proxies` in the Caddyfile, or every
  visitor will share Cloudflare's IPs for rate limiting.
- **YouTube blocks datacenter IPs.** Expect "Sign in to confirm you're not a bot"
  errors from cloud servers. Keep yt-dlp updated; you may need cookies or a proxy.
- **Legal:** downloading violates YouTube's Terms of Service, and public
  downloaders can receive DMCA notices. Add terms of use telling users to only
  download content they have rights to, and have a takedown contact.
