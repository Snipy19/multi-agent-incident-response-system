"""
LLM HELPER - Retry logic + Concurrency throttling
------------------------------------------------------
Purpose: provide exponential retry handling and concurrency throttling for Groq.
Only a limited number of calls reach the API at once; additional calls wait in
the queue to reduce rate-limit pressure during large investigator fan-outs.
"""

import time
import threading
import logging
from groq import RateLimitError, APIError

# At most three Groq calls run concurrently; additional calls wait in the queue.
_llm_semaphore = threading.Semaphore(3)
_logger = logging.getLogger("incident_response")


def invoke_with_retry(llm, prompt: str, max_retries: int = 6, base_delay: float = 3.0):
    """
    llm: ChatGroq instance
    prompt: prompt to send
    max_retries: number of retries after a transient failure
    base_delay: initial retry delay in seconds
    """
    # Hold the semaphore across retries so a rate-limited call does not allow
    # a large queued run to overwhelm the provider while backing off.
    with _llm_semaphore:
        for attempt in range(max_retries):
            started = time.perf_counter()
            try:
                response = llm.invoke(prompt)
                duration_ms = round((time.perf_counter() - started) * 1000, 1)
                usage = _usage_metadata(response)
                usage_fields = " ".join(
                    f"{key}={value}" for key, value in usage.items()
                )
                _logger.info(
                    "llm_call_completed attempt=%s duration_ms=%.1f%s",
                    attempt + 1,
                    duration_ms,
                    f" {usage_fields}" if usage_fields else "",
                )
                return response
            except (RateLimitError, APIError) as e:
                duration_ms = round((time.perf_counter() - started) * 1000, 1)
                if attempt == max_retries - 1:
                    _logger.warning(
                        "llm_call_failed attempt=%s duration_ms=%.1f error=%s retries_exhausted=true",
                        attempt + 1,
                        duration_ms,
                        type(e).__name__,
                    )
                    raise

                wait_time = base_delay * (2 ** attempt)  # 3s, 6s, 12s, 24s, 48s...
                _logger.warning(
                    "llm_call_retry attempt=%s duration_ms=%.1f error=%s "
                    "backoff_seconds=%.1f max_retries=%s",
                    attempt + 1,
                    duration_ms,
                    type(e).__name__,
                    wait_time,
                    max_retries,
                )
                time.sleep(wait_time)


def _usage_metadata(response) -> dict[str, int]:
    """Return provider-reported token counts only when the response supplies them."""
    metadata = getattr(response, "response_metadata", None)
    if not isinstance(metadata, dict):
        return {}
    usage = metadata.get("token_usage") or metadata.get("usage")
    if not isinstance(usage, dict):
        return {}
    allowed = {
        "prompt_tokens": "prompt_tokens",
        "completion_tokens": "completion_tokens",
        "total_tokens": "total_tokens",
    }
    result = {}
    for source, target in allowed.items():
        value = usage.get(source)
        if isinstance(value, int) and value >= 0:
            result[target] = value
    return result
