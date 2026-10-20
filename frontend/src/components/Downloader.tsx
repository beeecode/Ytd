"use client";

import { useEffect, useRef, useState } from "react";
import {
  type AudioFormat,
  type JobState,
  type Kind,
  type VideoInfo,
  createJob,
  fetchInfo,
  formatBytes,
  formatDuration,
  qualityLabel,
  watchJob,
} from "@/lib/api";

export default function Downloader() {
  const [url, setUrl] = useState("");
  const [info, setInfo] = useState<VideoInfo | null>(null);
  const [loadingInfo, setLoadingInfo] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [kind, setKind] = useState<Kind>("video");
  const [quality, setQuality] = useState<number | null>(null);
  const [audioFormat, setAudioFormat] = useState<AudioFormat>("mp3");

  const [job, setJob] = useState<JobState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const autoDownloaded = useRef<string | null>(null);

  // Live job updates over SSE.
  const jobId = job?.id;
  useEffect(() => {
    if (!jobId) return;
    return watchJob(jobId, setJob, (message) => setError(message));
  }, [jobId]);

  // Start the browser download once, as soon as the file is ready.
  useEffect(() => {
    if (job?.status === "finished" && job.file && autoDownloaded.current !== job.id) {
      autoDownloaded.current = job.id;
      triggerDownload(job.file.url);
    }
  }, [job]);

  async function handleFetch(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setError(null);
    setInfo(null);
    setJob(null);
    setLoadingInfo(true);
    try {
      const data = await fetchInfo(url.trim());
      setInfo(data);
      // Default to the best quality up to 1080p to keep files reasonable.
      setQuality(data.video_qualities.find((q) => q <= 1080) ?? data.video_qualities[0] ?? null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoadingInfo(false);
    }
  }

  async function handleDownload() {
    if (!info) return;
    setError(null);
    setSubmitting(true);
    try {
      setJob(await createJob({ url: info.webpage_url, kind, quality, audio_format: audioFormat }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  async function handlePaste() {
    try {
      const text = await navigator.clipboard.readText();
      if (text) setUrl(text.trim());
    } catch {
      // Clipboard permission denied; the user can paste manually.
    }
  }

  function reset() {
    setUrl("");
    setInfo(null);
    setJob(null);
    setError(null);
  }

  const busy = job !== null && !["finished", "failed", "stopped", "canceled"].includes(job.status);

  return (
    <div className="w-full space-y-6">
      <form onSubmit={handleFetch} className="flex flex-col gap-3 sm:flex-row">
        <div className="relative flex-1">
          <input
            type="url"
            inputMode="url"
            required
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="Paste a YouTube link…"
            aria-label="YouTube URL"
            disabled={busy}
            className="h-12 w-full rounded-xl border border-border bg-surface pl-4 pr-20 text-base outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/30 disabled:opacity-60"
          />
          <button
            type="button"
            onClick={handlePaste}
            disabled={busy}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg px-3 py-1.5 text-sm text-muted transition hover:bg-border/60 hover:text-foreground"
          >
            Paste
          </button>
        </div>
        <button
          type="submit"
          disabled={loadingInfo || busy}
          className="h-12 rounded-xl bg-accent px-6 font-semibold text-white transition hover:bg-accent-hover disabled:opacity-60"
        >
          {loadingInfo ? "Loading…" : "Get video"}
        </button>
      </form>

      {error && (
        <div role="alert" className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
          {error}
        </div>
      )}

      {loadingInfo && <InfoSkeleton />}

      {info && (
        <section className="overflow-hidden rounded-2xl border border-border bg-surface">
          <div className="flex flex-col gap-4 p-4 sm:flex-row">
            {info.thumbnail && (
              <div className="relative aspect-video w-full shrink-0 overflow-hidden rounded-lg bg-border sm:w-56">
                {/* eslint-disable-next-line @next/next/no-img-element -- remote thumbnail, no need to proxy through the optimizer */}
                <img src={info.thumbnail} alt="" className="h-full w-full object-cover" />
                {info.duration ? (
                  <span className="absolute bottom-1.5 right-1.5 rounded bg-black/80 px-1.5 py-0.5 text-xs font-medium text-white">
                    {formatDuration(info.duration)}
                  </span>
                ) : null}
              </div>
            )}
            <div className="min-w-0 flex-1">
              <h2 className="line-clamp-2 text-lg font-semibold leading-snug">{info.title}</h2>
              {info.uploader && <p className="mt-1 text-sm text-muted">{info.uploader}</p>}
            </div>
          </div>

          <div className="space-y-4 border-t border-border p-4">
            {job ? (
              <JobPanel job={job} onReset={reset} onRetry={handleDownload} />
            ) : (
              <>
                <div className="inline-flex rounded-lg bg-border/50 p-1" role="tablist">
                  {(["video", "audio"] as const).map((k) => (
                    <button
                      key={k}
                      role="tab"
                      aria-selected={kind === k}
                      onClick={() => setKind(k)}
                      className={`rounded-md px-4 py-1.5 text-sm font-medium transition ${
                        kind === k ? "bg-surface shadow-sm" : "text-muted hover:text-foreground"
                      }`}
                    >
                      {k === "video" ? "Video (MP4)" : "Audio only"}
                    </button>
                  ))}
                </div>

                <div className="flex flex-wrap gap-2">
                  {kind === "video"
                    ? info.video_qualities.map((q) => (
                        <Chip key={q} active={quality === q} onClick={() => setQuality(q)}>
                          {qualityLabel(q)}
                        </Chip>
                      ))
                    : (["mp3", "m4a"] as const).map((f) => (
                        <Chip key={f} active={audioFormat === f} onClick={() => setAudioFormat(f)}>
                          {f.toUpperCase()}
                        </Chip>
                      ))}
                </div>

                <button
                  onClick={handleDownload}
                  disabled={submitting}
                  className="h-11 w-full rounded-xl bg-accent font-semibold text-white transition hover:bg-accent-hover disabled:opacity-60"
                >
                  {submitting ? "Starting…" : "Download"}
                </button>
              </>
            )}
          </div>
        </section>
      )}
    </div>
  );
}

function JobPanel({ job, onReset, onRetry }: { job: JobState; onReset: () => void; onRetry: () => void }) {
  const p = job.progress;

  if (job.status === "finished" && job.file) {
    return (
      <div className="space-y-3">
        <p className="text-sm">
          <span className="font-semibold text-green-600 dark:text-green-400">Ready!</span>{" "}
          <span className="text-muted">Your download should start automatically.</span>
        </p>
        <p className="truncate text-sm text-muted" title={job.file.filename}>
          {job.file.filename} · {formatBytes(job.file.filesize)}
        </p>
        <div className="flex gap-2">
          <a
            href={job.file.url}
            className="flex h-11 flex-1 items-center justify-center rounded-xl bg-accent font-semibold text-white transition hover:bg-accent-hover"
          >
            Download file
          </a>
          <button onClick={onReset} className="h-11 rounded-xl border border-border px-4 font-medium transition hover:bg-border/50">
            New download
          </button>
        </div>
        <p className="text-xs text-muted">Files are deleted from our server after one hour.</p>
      </div>
    );
  }

  if (["failed", "stopped", "canceled"].includes(job.status)) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-red-600 dark:text-red-400">{job.error ?? "Download failed."}</p>
        <div className="flex gap-2">
          <button onClick={onRetry} className="h-11 flex-1 rounded-xl bg-accent font-semibold text-white hover:bg-accent-hover">
            Try again
          </button>
          <button onClick={onReset} className="h-11 rounded-xl border border-border px-4 font-medium hover:bg-border/50">
            Start over
          </button>
        </div>
      </div>
    );
  }

  let label = "Preparing…";
  let detail = "";
  if (job.status === "queued") {
    label = "Waiting in queue…";
    if (job.position != null) detail = `Position ${job.position + 1}`;
  } else if (p?.stage === "downloading") {
    label = p.percent != null ? `Downloading… ${Math.round(p.percent)}%` : "Downloading…";
    detail = [p.speed ? `${formatBytes(p.speed)}/s` : "", p.eta ? `${formatDuration(p.eta)} left` : ""]
      .filter(Boolean)
      .join(" · ");
  } else if (p?.stage === "processing") {
    label = "Processing…";
    detail = "Merging and converting";
  }

  const percent = p?.stage === "downloading" ? p.percent : null;

  return (
    <div className="space-y-2" aria-live="polite">
      <div className="flex items-baseline justify-between gap-4 text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-muted">{detail}</span>
      </div>
      <div className="h-2.5 overflow-hidden rounded-full bg-border" role="progressbar" aria-valuenow={percent ?? undefined} aria-valuemin={0} aria-valuemax={100}>
        {percent != null ? (
          <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${percent}%` }} />
        ) : (
          <div className="h-full w-1/3 animate-indeterminate rounded-full bg-accent" />
        )}
      </div>
    </div>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-lg border px-3.5 py-1.5 text-sm font-medium transition ${
        active ? "border-accent bg-accent/10 text-accent" : "border-border hover:border-muted"
      }`}
    >
      {children}
    </button>
  );
}

function InfoSkeleton() {
  return (
    <div className="flex animate-pulse gap-4 rounded-2xl border border-border bg-surface p-4">
      <div className="aspect-video w-56 rounded-lg bg-border" />
      <div className="flex-1 space-y-2 pt-1">
        <div className="h-4 w-3/4 rounded bg-border" />
        <div className="h-4 w-1/2 rounded bg-border" />
        <div className="h-3 w-1/4 rounded bg-border" />
      </div>
    </div>
  );
}

function triggerDownload(href: string) {
  const a = document.createElement("a");
  a.href = href;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
