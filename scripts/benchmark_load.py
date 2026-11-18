"""Run real local load-test analyses and write reproducible measurements.

This runner uses the public API and the existing ``load_test`` mode. It does
not replace the LLM, RAG retriever, worker, or persistence layer with mocks.
Use a dedicated local benchmark account because each completed job is a real
analysis and is retained in the analysis-job history. The resulting incident
is deleted after its metrics are captured unless ``--keep-incidents`` is set.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import platform
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_TARGETS = (1, 10, 25, 50, 100)
DEFAULT_CONTAINER = "incident-response-api"
BENCHMARK_LOG = """2026-10-31T10:00:00Z CRITICAL benchmark checkout-api returned HTTP 503 for 18% of requests.
P95 latency increased from 220ms to 7.4s.
PostgreSQL connection attempts to db-primary.internal timed out after 30 seconds.
Redis inventory reads increased to 2.8 seconds.
Kafka order-events consumer lag reached 31,000 messages.
DNS lookups for db-primary.internal intermittently failed.
Two checkout-api pods failed readiness probes and restarted.
CPU was 58%, memory was 71%, and disk usage was 54%.
No credentials, API keys, tokens, or customer data are included.
"""


class BenchmarkError(RuntimeError):
    """A safe benchmark failure without provider response bodies or credentials."""


def _json_request(opener, url: str, method: str, payload: dict | None = None):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail")
        except (ValueError, UnicodeDecodeError):
            detail = None
        raise BenchmarkError(
            f"{method} {urlparse_path(url)} returned HTTP {exc.code}"
            + (f": {detail}" if detail else "")
        ) from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise BenchmarkError(f"{method} {urlparse_path(url)} failed: {type(exc).__name__}") from None


def urlparse_path(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return parsed.path or "/"


def _memory_sample_mb(container: str) -> float | None:
    """Read a point-in-time Docker memory sample; return None if unavailable."""
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    match = re.match(r"\s*([0-9.]+)\s*([KMGT]?i?B)", result.stdout.strip())
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).upper()
    multipliers = {"B": 1, "KB": 1000, "KIB": 1024, "MB": 1000**2, "MIB": 1024**2,
                   "GB": 1000**3, "GIB": 1024**3, "TB": 1000**4, "TIB": 1024**4}
    multiplier = multipliers.get(unit)
    return round(value * multiplier / (1024**2), 2) if multiplier else None


def _parse_targets(value: str) -> list[int]:
    targets = []
    for part in value.split(","):
        try:
            target = int(part.strip())
        except ValueError as exc:
            raise BenchmarkError(f"Invalid benchmark target: {part!r}") from exc
        if target not in range(1, 101):
            raise BenchmarkError(f"Benchmark target must be between 1 and 100: {target}")
        if target not in targets:
            targets.append(target)
    if not targets:
        raise BenchmarkError("At least one benchmark target is required")
    return targets


def _write_result(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run(args) -> int:
    base_url = args.base_url.rstrip("/")
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        if not args.allow_nonlocal:
            raise BenchmarkError(
                "Refusing non-local benchmark target. Use --allow-nonlocal only with explicit approval."
            )

    username = os.getenv("BENCHMARK_USERNAME", "").strip()
    password = os.getenv("BENCHMARK_PASSWORD", "")
    if not username or not password:
        raise BenchmarkError("Set BENCHMARK_USERNAME and BENCHMARK_PASSWORD in the shell first")

    log_text = Path(args.log_file).read_text(encoding="utf-8") if args.log_file else BENCHMARK_LOG
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    _json_request(opener, f"{base_url}/login", "POST", {"username": username, "password": password})

    targets = _parse_targets(args.targets)
    results = []
    for target in targets:
        started = time.perf_counter()
        _, queued = _json_request(
            opener,
            f"{base_url}/analyze/jobs",
            "POST",
            {
                "raw_log": log_text,
                "agent_mode": "load_test",
                "target_agent_count": target,
            },
        )
        job_id = queued.get("job_id")
        if not job_id:
            raise BenchmarkError("The API did not return a benchmark job id")

        memory_samples = []
        deadline = time.monotonic() + args.timeout
        status = None
        while time.monotonic() < deadline:
            _, status = _json_request(opener, f"{base_url}/analyze/jobs/{job_id}", "GET")
            memory = _memory_sample_mb(args.container)
            if memory is not None:
                memory_samples.append(memory)
            if status.get("status") in {"completed", "failed"}:
                break
            time.sleep(args.poll)
        else:
            raise BenchmarkError(f"Benchmark job {job_id} exceeded the configured timeout")

        incident_id = ((status.get("result") or {}).get("incident_id"))
        deleted = None
        if incident_id and not args.keep_incidents:
            delete_status, _ = _json_request(opener, f"{base_url}/incidents/{incident_id}", "DELETE")
            deleted = delete_status == 200

        metrics = status.get("metrics") or {}
        results.append({
            "target_agents": target,
            "job_id": job_id,
            "status": status.get("status"),
            "wall_duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "input_bytes": len(log_text.encode("utf-8")),
            "input_lines": len(log_text.splitlines()),
            "metrics": metrics,
            "memory_peak_sample_mb": max(memory_samples) if memory_samples else None,
            "memory_sample_count": len(memory_samples),
            "incident_deleted": deleted,
        })
        print(
            f"target={target} status={status.get('status')} "
            f"wall_duration_ms={results[-1]['wall_duration_ms']} "
            f"llm_calls={metrics.get('llm_calls')} cost_usd={metrics.get('cost_usd')}"
        )

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "benchmark_mode": "load_test",
        "targets": targets,
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
        },
        "input": {
            "bytes": len(log_text.encode("utf-8")),
            "lines": len(log_text.splitlines()),
            "source": args.log_file or "built-in redacted benchmark log",
        },
        "results": results,
    }
    _write_result(Path(args.output), output)
    print(f"Wrote benchmark results to {args.output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("BENCHMARK_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--targets", default=os.getenv("BENCHMARK_TARGETS", "1,10,25,50,100"))
    parser.add_argument("--output", default="benchmarks/results/latest.json")
    parser.add_argument("--log-file")
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    parser.add_argument("--poll", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--keep-incidents", action="store_true")
    parser.add_argument("--allow-nonlocal", action="store_true")
    args = parser.parse_args()
    try:
        return run(args)
    except BenchmarkError as exc:
        print(f"Benchmark stopped: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
