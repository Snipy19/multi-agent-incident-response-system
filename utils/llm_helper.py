"""
LLM HELPER - Retry logic + Concurrency throttling
------------------------------------------------------
Purpose: provide exponential retry handling and concurrency throttling for Groq.
Only a limited number of calls reach the API at once; additional calls wait in
the queue to reduce rate-limit pressure during large investigator fan-outs.
"""

import time
import threading
import os
from dotenv import load_dotenv
from groq import RateLimitError, APIError

load_dotenv()


def _positive_int_setting(name: str, default: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return min(max(value, 1), maximum)


def _positive_float_setting(name: str, default: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return min(max(value, 0.1), maximum)


# At most three Groq calls run concurrently by default; additional calls wait
# in the queue to reduce provider pressure during large investigator fan-outs.
LLM_MAX_CONCURRENCY = _positive_int_setting("LLM_MAX_CONCURRENCY", 3, 32)
LLM_MAX_ATTEMPTS = _positive_int_setting("LLM_MAX_ATTEMPTS", 6, 10)
LLM_RETRY_BASE_DELAY_SECONDS = _positive_float_setting(
    "LLM_RETRY_BASE_DELAY_SECONDS", 3.0, 60.0
)
LLM_TIMEOUT_SECONDS = _positive_float_setting("LLM_TIMEOUT_SECONDS", 60.0, 300.0)
_llm_semaphore = threading.BoundedSemaphore(LLM_MAX_CONCURRENCY)


def invoke_with_retry(
    llm,
    prompt: str,
    max_retries: int | None = None,
    base_delay: float | None = None,
):
    """
    llm: ChatGroq instance
    prompt: prompt to send
    max_retries: maximum number of provider attempts
    base_delay: initial retry delay in seconds
    """
    attempts = max_retries if max_retries is not None else LLM_MAX_ATTEMPTS
    delay = base_delay if base_delay is not None else LLM_RETRY_BASE_DELAY_SECONDS
    attempts = min(max(int(attempts), 1), 10)
    delay = min(max(float(delay), 0.1), 60.0)

    # Hold the semaphore across retries so a rate-limited call does not allow
    # a large queued run to overwhelm the provider while backing off.
    with _llm_semaphore:
        for attempt in range(attempts):
            try:
                response = llm.invoke(prompt)
                return response
            except (RateLimitError, APIError) as e:
                if attempt == attempts - 1:
                    print(
                        "[LLM HELPER] Maximum retries exhausted: "
                        f"{type(e).__name__}"
                    )
                    raise

                wait_time = delay * (2 ** attempt)
                print(
                    "[LLM HELPER] Transient API error "
                    f"({type(e).__name__}); retrying in {wait_time}s "
                    f"(attempt {attempt + 1}/{attempts})..."
                )
                time.sleep(wait_time)
