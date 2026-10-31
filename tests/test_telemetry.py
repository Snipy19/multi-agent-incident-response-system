from utils.telemetry import finish_run, record_llm_attempt, start_run
from utils.llm_helper import _usage_metadata


def test_usage_metadata_accepts_langchain_provider_shape():
    class Response:
        usage_metadata = {
            "input_tokens": 12,
            "output_tokens": 7,
            "total_tokens": 19,
        }

    assert _usage_metadata(Response()) == {
        "prompt_tokens": 12,
        "completion_tokens": 7,
        "total_tokens": 19,
    }


def test_telemetry_keeps_cost_unknown_without_explicit_pricing(monkeypatch):
    monkeypatch.delenv("LLM_INPUT_COST_PER_1M_USD", raising=False)
    monkeypatch.delenv("LLM_OUTPUT_COST_PER_1M_USD", raising=False)

    start_run("run-unknown-cost")
    record_llm_attempt(
        "run-unknown-cost",
        attempt=1,
        duration_ms=120.5,
        usage={"prompt_tokens": 100, "completion_tokens": 40},
        success=True,
    )

    metrics = finish_run("run-unknown-cost")

    assert metrics["llm_calls"] == 1
    assert metrics["llm_retries"] == 0
    assert metrics["llm_call_failures"] == 0
    assert metrics["token_usage"] == {"prompt_tokens": 100, "completion_tokens": 40}
    assert metrics["cost_usd"] is None
    assert metrics["cost_status"] == "unavailable"


def test_telemetry_calculates_cost_only_from_explicit_rates(monkeypatch):
    monkeypatch.setenv("LLM_INPUT_COST_PER_1M_USD", "1.5")
    monkeypatch.setenv("LLM_OUTPUT_COST_PER_1M_USD", "3")

    start_run("run-known-cost")
    record_llm_attempt(
        "run-known-cost",
        attempt=1,
        duration_ms=100,
        usage={"prompt_tokens": 1_000_000, "completion_tokens": 2_000_000},
        success=False,
    )
    record_llm_attempt(
        "run-known-cost",
        attempt=2,
        duration_ms=200,
        usage={"prompt_tokens": 1_000_000, "completion_tokens": 2_000_000},
        success=True,
    )

    metrics = finish_run("run-known-cost")

    assert metrics["llm_calls"] == 2
    assert metrics["llm_retries"] == 1
    assert metrics["llm_call_failures"] == 1
    assert metrics["token_usage"] == {
        "prompt_tokens": 2_000_000,
        "completion_tokens": 4_000_000,
    }
    assert metrics["cost_usd"] == 15.0
    assert metrics["cost_status"] == "calculated"
