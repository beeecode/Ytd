// Client for the FastAPI backend. All paths are same-origin (/api/...).

export type VideoInfo = {
  id: string;
  title: string;
  uploader: string | null;
  duration: number | null;
  thumbnail: string | null;
  webpage_url: string;
  video_qualities: number[];
};

export type Kind = "video" | "audio";
export type AudioFormat = "mp3" | "m4a";

export type JobProgress = {
  stage: "downloading" | "processing";
  percent: number | null;
  downloaded_bytes?: number;
  total_bytes?: number | null;
  speed?: number | null;
  eta?: number | null;
};

export type JobState = {
  id: string;
  status: "queued" | "started" | "finished" | "failed" | "stopped" | "canceled" | "deferred" | "scheduled";
  progress: JobProgress | null;
  position?: number | null;
  error?: string;
  file?: { filename: string; filesize: number; url: string };
};

export const TERMINAL: JobState["status"][] = ["finished", "failed", "stopped", "canceled"];

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === "string" ? detail : "Something went wrong. Please try again.");
  }
  return data as T;
}

export function fetchInfo(url: string) {
  return post<VideoInfo>("/api/info", { url });
}

export function createJob(req: {
  url: string;
  kind: Kind;
  quality: number | null;
  audio_format: AudioFormat;
}) {
  return post<JobState>("/api/jobs", req);
}

/** Subscribe to live job updates. Returns an unsubscribe function. */
export function watchJob(
  id: string,
  onUpdate: (state: JobState) => void,
  onError: (message: string) => void,
): () => void {
  const source = new EventSource(`/api/jobs/${id}/events`);
  source.onmessage = (e) => {
    const state = JSON.parse(e.data) as JobState;
    onUpdate(state);
    if (TERMINAL.includes(state.status)) source.close();
  };
  source.addEventListener("error", (e) => {
    // A named "error" event from the server carries a message; a plain
    // error event means the connection dropped.
    const data = (e as MessageEvent).data;
    if (data) {
      onError(JSON.parse(data).error ?? "Job expired.");
      source.close();
    } else if (source.readyState === EventSource.CLOSED) {
      onError("Lost connection to the server.");
    }
    // Otherwise EventSource reconnects automatically.
  });
  return () => source.close();
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return "";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let n = bytes;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}

export function qualityLabel(height: number): string {
  if (height >= 2160) return "4K";
  if (height >= 1440) return "1440p";
  return `${height}p`;
}
