from utils.llm_helper import (
    LLM_MAX_ATTEMPTS,
    LLM_MAX_CONCURRENCY,
    LLM_RETRY_BASE_DELAY_SECONDS,
    LLM_TIMEOUT_SECONDS,
    invoke_with_retry,
)


class ImmediateModel:
    def __init__(self):
        self.calls = 0

    def invoke(self, prompt):
        self.calls += 1
        return {"prompt": prompt}


def test_llm_helper_returns_real_provider_response_without_extra_attempts():
    model = ImmediateModel()

    response = invoke_with_retry(model, "incident evidence", max_retries=1)

    assert response == {"prompt": "incident evidence"}
    assert model.calls == 1


def test_llm_runtime_limits_are_positive_and_bounded():
    assert 1 <= LLM_MAX_CONCURRENCY <= 32
    assert 1 <= LLM_MAX_ATTEMPTS <= 10
    assert 0.1 <= LLM_RETRY_BASE_DELAY_SECONDS <= 60
    assert 0.1 <= LLM_TIMEOUT_SECONDS <= 300
