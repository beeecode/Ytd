import Downloader from "@/components/Downloader";

export default function Home() {
  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="mx-auto flex w-full max-w-2xl items-center gap-2 px-4 py-5">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-white" aria-hidden>
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor">
            <path d="M12 16l-5-5h3V4h4v7h3l-5 5zm-7 2h14v2H5v-2z" />
          </svg>
        </span>
        <span className="text-lg font-bold tracking-tight">Ytd</span>
      </header>

      <main className="mx-auto w-full max-w-2xl flex-1 px-4 pb-16 pt-8 sm:pt-16">
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">YouTube Downloader</h1>
          <p className="mt-3 text-muted">Download videos as MP4 or extract audio as MP3. Free, no sign-up.</p>
        </div>
        <Downloader />
      </main>

      <footer className="mx-auto w-full max-w-2xl px-4 py-6 text-center text-xs text-muted">
        Only download content you own or have permission to use. Ytd is not affiliated with YouTube.
      </footer>
    </div>
  );
}
