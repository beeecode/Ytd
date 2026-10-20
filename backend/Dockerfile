FROM python:3.13-slim

# ffmpeg merges video+audio and converts to MP3; Deno is the JS runtime
# yt-dlp needs to solve YouTube's player challenges.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=denoland/deno:bin-2.5.6 /deno /usr/local/bin/deno

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --create-home ytd && mkdir -p /data/downloads && chown ytd /data/downloads
USER ytd

ENV DOWNLOAD_DIR=/data/downloads \
    PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
