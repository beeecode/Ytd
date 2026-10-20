"""Worker entry point: `python -m app.worker`."""

import sys

from rq import SimpleWorker, Worker
from rq.timeouts import TimerDeathPenalty

from .broker import download_queue, redis_conn


class WindowsWorker(SimpleWorker):
    # Windows has no fork() or SIGALRM, so run jobs in-process with a
    # thread-based timeout. Fine for local development; production runs
    # the regular forking Worker on Linux.
    death_penalty_class = TimerDeathPenalty


def main() -> None:
    worker_cls = WindowsWorker if sys.platform == "win32" else Worker
    worker = worker_cls([download_queue], connection=redis_conn)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
