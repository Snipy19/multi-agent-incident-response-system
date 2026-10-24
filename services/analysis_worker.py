"""Durable local analysis queue worker.

Jobs are stored in SQLite before execution, so a request is not lost between
HTTP submission and graph execution. This is the local worker boundary that
can later be replaced by SQS/Celery/RQ when the service moves to AWS.
"""

import threading
import uuid
import sqlite3

from db.database import (
    claim_next_analysis_job,
    complete_analysis_job,
    fail_analysis_job,
    save_incident,
)


class AnalysisWorker:
    def __init__(self, poll_seconds: float = 0.5):
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="analysis-job-worker",
            daemon=True,
        )
        self._thread.start()
        print("[JOBS] Analysis worker started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = claim_next_analysis_job()
            except sqlite3.OperationalError as exc:
                # A deployment may briefly point at a database before its
                # migration has run. Keep the worker alive and retry instead
                # of losing the queue thread to an unhandled exception.
                print(f"[JOBS] Queue unavailable; retrying: {exc}")
                self._stop.wait(self.poll_seconds)
                continue
            if job is None:
                self._stop.wait(self.poll_seconds)
                continue
            self._execute(job)

    @staticmethod
    def _execute(job: dict) -> None:
        try:
            # Import the graph only inside the worker. Authentication, health
            # checks, and job submission never load the expensive LLM/RAG stack.
            from graph import app as graph_app

            result = graph_app.invoke(job["request_state"])
            incident_id = str(uuid.uuid4())
            save_incident(incident_id, job["user_id"], result)
            complete_analysis_job(job["id"], {"incident_id": incident_id})
            print(f"[JOBS] Analysis job {job['id']} completed")
        except Exception as exc:
            fail_analysis_job(job["id"], str(exc))
            print(f"[JOBS] Analysis job {job['id']} failed: {exc}")


_worker = AnalysisWorker()


def start_analysis_worker() -> None:
    _worker.start()


def stop_analysis_worker() -> None:
    _worker.stop()
