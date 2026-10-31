"""Real per-analysis telemetry with explicit unknowns instead of estimates."""

from __future__ import annotations

import math
import os
import threading
from dataclasses import dataclass, field


def _configured_rate(name: str) -> float | None:
    """Read a non-negative USD-per-million-token rate, if explicitly configured."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


@dataclass
class _RunTelemetry:
    lock: threading.Lock = field(default_factory=threading.Lock)
    llm_calls: int = 0
    llm_retries: int = 0
    llm_call_failures: int = 0
    llm_duration_ms: float = 0.0
    token_usage: dict[str, int] = field(default_factory=dict)

    def record_attempt(
        self,
        *,
        attempt: int,
        duration_ms: float,
        usage: dict[str, int],
        success: bool,
    ) -> None:
        with self.lock:
            self.llm_calls += 1
            self.llm_retries += max(attempt - 1, 0)
            if not success:
                self.llm_call_failures += 1
            self.llm_duration_ms += max(float(duration_ms), 0.0)
            for key, value in usage.items():
                if isinstance(value, int) and value >= 0:
                    self.token_usage[key] = self.token_usage.get(key, 0) + value

    def snapshot(self) -> dict:
        with self.lock:
            token_usage = dict(self.token_usage)
            input_rate = _configured_rate("LLM_INPUT_COST_PER_1M_USD")
            output_rate = _configured_rate("LLM_OUTPUT_COST_PER_1M_USD")
            prompt_tokens = token_usage.get("prompt_tokens")
            completion_tokens = token_usage.get("completion_tokens")
            cost_usd = None
            cost_status = "unavailable"
            if (
                input_rate is not None
                and output_rate is not None
                and prompt_tokens is not None
                and completion_tokens is not None
            ):
                cost_usd = round(
                    (prompt_tokens * input_rate + completion_tokens * output_rate)
                    / 1_000_000,
                    8,
                )
                cost_status = "calculated"

            return {
                "llm_calls": self.llm_calls,
                "llm_retries": self.llm_retries,
                "llm_call_failures": self.llm_call_failures,
                "llm_duration_ms": round(self.llm_duration_ms, 1),
                "token_usage": token_usage,
                "cost_usd": cost_usd,
                "cost_status": cost_status,
            }


_registry_lock = threading.Lock()
_active_runs: dict[str, _RunTelemetry] = {}


def start_run(run_id: str) -> None:
    with _registry_lock:
        _active_runs[run_id] = _RunTelemetry()


def record_llm_attempt(
    run_id: str | None,
    *,
    attempt: int,
    duration_ms: float,
    usage: dict[str, int],
    success: bool,
) -> None:
    if not run_id:
        return
    with _registry_lock:
        run = _active_runs.get(run_id)
    if run is not None:
        run.record_attempt(
            attempt=attempt,
            duration_ms=duration_ms,
            usage=usage,
            success=success,
        )


def finish_run(run_id: str) -> dict:
    with _registry_lock:
        run = _active_runs.pop(run_id, None)
    return run.snapshot() if run is not None else {
        "llm_calls": 0,
        "llm_retries": 0,
        "llm_call_failures": 0,
        "llm_duration_ms": 0.0,
        "token_usage": {},
        "cost_usd": None,
        "cost_status": "unavailable",
    }
