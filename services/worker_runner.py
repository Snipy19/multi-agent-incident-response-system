"""Standalone entrypoint for a deployment-separated analysis worker."""

import signal
import threading

from db.database import init_db
from services.analysis_worker import start_analysis_worker, stop_analysis_worker


def main() -> None:
    init_db()
    stop_requested = threading.Event()

    def request_stop(_signum, _frame):
        stop_requested.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    start_analysis_worker()
    try:
        while not stop_requested.wait(1):
            pass
    finally:
        stop_analysis_worker()


if __name__ == "__main__":
    main()
