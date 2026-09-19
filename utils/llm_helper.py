"""
LLM HELPER - Retry logic + Concurrency throttling
------------------------------------------------------
Kaam: Groq API ko call karte waqt:
1. Agar RATE LIMIT ya temporary error aaye, exponential backoff se retry karo
2. Concurrency ko limit karo - ek time pe sirf N calls Groq tak jaane do,
   baaki queue mein wait karein. Ye zaroori hai jab 20-50 investigators
   ek saath parallel spawn hote hain - sabko ek saath LLM hit karne dena
   rate limit ko turant exhaust kar deta hai, chahe retry logic ho bhi.
"""

import time
import threading
from groq import RateLimitError, APIError

# Concurrency limiter: ek time pe max 3 LLM calls Groq ko jaayengi,
# baaki calls yahan wait karengi apni baari ke liye. Chahe 50 investigators
# spawn hon, sirf 3 ek saath actual API hit karenge - baaki queue mein.
_llm_semaphore = threading.Semaphore(3)


def invoke_with_retry(llm, prompt: str, max_retries: int = 6, base_delay: float = 3.0):
    """
    llm: ChatGroq instance
    prompt: jo prompt bhejna hai
    max_retries: kitni baar retry karna hai fail hone par
    base_delay: pehli retry se pehle kitna wait karna hai (seconds mein)
    """
    with _llm_semaphore:
        for attempt in range(max_retries):
            try:
                response = llm.invoke(prompt)
                return response
            except (RateLimitError, APIError) as e:
                if attempt == max_retries - 1:
                    print(f"[LLM HELPER] Max retries khatam, fail ho gaya: {e}")
                    raise

                wait_time = base_delay * (2 ** attempt)  # 3s, 6s, 12s, 24s, 48s...
                print(f"[LLM HELPER] Rate limit/error mila, {wait_time}s wait karke retry kar rahe hain (attempt {attempt + 1}/{max_retries})...")
                time.sleep(wait_time)