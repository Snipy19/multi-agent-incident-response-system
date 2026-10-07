"""
LLM HELPER - Retry logic + Concurrency throttling
------------------------------------------------------
Purpose: provide exponential retry handling and concurrency throttling for Groq.
Only a limited number of calls reach the API at once; additional calls wait in
the queue to reduce rate-limit pressure during large investigator fan-outs.
"""

import time
import threading
from groq import RateLimitError, APIError

# At most three Groq calls run concurrently; additional calls wait in the queue.
_llm_semaphore = threading.Semaphore(3)


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
            try:
                response = llm.invoke(prompt)
                return response
            except (RateLimitError, APIError) as e:
                if attempt == max_retries - 1:
                    print(f"[LLM HELPER] Maximum retries exhausted: {e}")
                    raise

                wait_time = base_delay * (2 ** attempt)  # 3s, 6s, 12s, 24s, 48s...
                print(f"[LLM HELPER] Transient API error; retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(wait_time)
