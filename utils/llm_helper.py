"""
LLM HELPER - Retry logic with exponential backoff
------------------------------------------------------
Kaam: Groq API ko call karte waqt agar RATE LIMIT ya temporary error
aaye, toh turant crash hone ke bajaye thoda wait karke dobara try karo.

Ye production-grade error handling hai - real systems mein LLM APIs
kabhi kabhi rate-limit ya timeout dete hain, isko handle karna zaroori hai.
"""

import time
from groq import RateLimitError, APIError


def invoke_with_retry(llm, prompt: str, max_retries: int = 4, base_delay: float = 2.0):
    """
    llm: ChatGroq instance
    prompt: jo prompt bhejna hai
    max_retries: kitni baar retry karna hai fail hone par
    base_delay: pehli retry se pehle kitna wait karna hai (seconds mein)

    Har retry pe wait time DOUBLE hota jaata hai (exponential backoff) -
    taaki agar server busy hai, hum usko aur pressure na dein.
    """
    for attempt in range(max_retries):
        try:
            response = llm.invoke(prompt)
            return response
        except (RateLimitError, APIError) as e:
            if attempt == max_retries - 1:
                # Last attempt bhi fail hui - ab error aage bhejo
                print(f"[LLM HELPER] Max retries khatam, fail ho gaya: {e}")
                raise

            wait_time = base_delay * (2 ** attempt)  # 2s, 4s, 8s, 16s...
            print(f"[LLM HELPER] Rate limit/error mila, {wait_time}s wait karke retry kar rahe hain (attempt {attempt + 1}/{max_retries})...")
            time.sleep(wait_time)