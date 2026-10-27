"""Durable local analysis queue worker.

Jobs are stored in SQLite before execution, so a request is not lost between
HTTP submission and graph execution. This is the local worker boundary that
can later be replaced by SQS/Celery/RQ when the service moves to AWS.
"""

import threading
import uuid
import sqlite3
import time
from datetime import datetime, timezone

from db.database import (
    append_analysis_job_event,
    claim_next_analysis_job,
    complete_analysis_job,
    fail_analysis_job,
    heartbeat_analysis_job,
    requeue_stale_analysis_jobs,
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
                print(f"[JOBS] Queue unavailable; retrying: {type(exc).__name__}")
                self._stop.wait(self.poll_seconds)
                continue
            if job is None:
                self._stop.wait(self.poll_seconds)
                continue
            self._execute(job)

    @staticmethod
    def _execute(job: dict) -> None:
        job_started = time.perf_counter()
        try:
            # Import the graph only inside the worker. Authentication, health
            # checks, and job submission never load the expensive LLM/RAG stack.
            from graph import app as graph_app

            current_state = dict(job["request_state"])
            current_state["investigation_findings"] = []
            heartbeat_analysis_job(job["id"])
            queue_wait_ms = _elapsed_between_iso(job.get("created_at"), job.get("started_at"))
            append_analysis_job_event(job["id"], {
                "type": "started",
                "stage": "worker",
                "message": "Analysis worker started.",
                "queue_wait_ms": queue_wait_ms,
            })
            stage_started = time.perf_counter()
            for update in graph_app.stream(job["request_state"], stream_mode="updates"):
                for node, node_update in update.items():
                    if not isinstance(node_update, dict):
                        continue
                    if node == "investigator":
                        current_state["investigation_findings"].extend(
                            node_update.get("investigation_findings") or []
                        )
                        findings = node_update.get("investigation_findings") or []
                        angle = findings[0].get("angle", "unknown angle") if findings else "unknown angle"
                        event = {
                            "type": "investigator",
                            "stage": "investigator",
                            "message": f"Investigator completed: {angle}.",
                            "angle": angle,
                        }
                    else:
                        current_state.update({
                            key: value
                            for key, value in node_update.items()
                            if key != "investigation_findings"
                        })
                        labels = {
                            "triage_planner": "Triage planner completed.",
                            "aggregator": "Aggregator completed.",
                            "fix_suggester": "Remediation recommendation completed.",
                            "report_writer": "Report preparation completed.",
                        }
                        event = {
                            "type": "stage",
                            "stage": node,
                            "message": labels.get(node, f"{node} completed."),
                        }
                    event["duration_ms"] = round((time.perf_counter() - stage_started) * 1000, 1)
                    stage_started = time.perf_counter()
                    heartbeat_analysis_job(job["id"])
                    append_analysis_job_event(job["id"], event)

            result = current_state
            incident_id = str(uuid.uuid4())
            save_incident(incident_id, job["user_id"], result)
            append_analysis_job_event(job["id"], {
                "type": "complete",
                "stage": "complete",
                "message": "Analysis complete.",
                "incident_id": incident_id,
                "duration_ms": round((time.perf_counter() - job_started) * 1000, 1),
            })
            complete_analysis_job(job["id"], {"incident_id": incident_id})
            print(
                f"[JOBS] Analysis job {job['id']} completed "
                f"duration_ms={round((time.perf_counter() - job_started) * 1000, 1)}"
            )
        except Exception as exc:
            append_analysis_job_event(job["id"], {
                "type": "error",
                "stage": "error",
                "message": "Analysis failed. Check the service logs for details.",
            })
            fail_analysis_job(job["id"], type(exc).__name__)
            print(
                f"[JOBS] Analysis job {job['id']} failed: "
                f"{type(exc).__name__}"
            )


def _elapsed_between_iso(start: str | None, end: str | None) -> float | None:
    """Return real queue wait in milliseconds when both timestamps exist."""
    if not start or not end:
        return None
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        return round(max((end_dt - start_dt).total_seconds() * 1000, 0), 1)
    except (TypeError, ValueError):
        return None


_worker = AnalysisWorker()


def start_analysis_worker() -> None:
    requeue_stale_analysis_jobs()
    _worker.start()


def stop_analysis_worker() -> None:
    _worker.stop()
