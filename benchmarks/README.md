# Real load benchmarks

`../scripts/benchmark_load.py` exercises the existing Docker API and real
LangGraph/LLM/RAG path in `load_test` mode. It does not mock the provider or
invent latency, token, cost, or memory values.

Use a dedicated local benchmark account. The runner deletes each completed
incident after collecting its metrics unless `--keep-incidents` is supplied.
Analysis-job records remain available for the metrics summary.

PowerShell example:

```powershell
$env:BENCHMARK_USERNAME = "your-local-benchmark-user"
$env:BENCHMARK_PASSWORD = "your-local-benchmark-password"
python scripts/benchmark_load.py
```

The default targets are 1, 10, 25, 50, and 100 investigators. The output is
written to `benchmarks/results/latest.json` and includes host information,
input size, wall-clock duration, queue/execution/LLM metrics, model metadata,
provider-reported token usage, cost when explicitly configured, and sampled
Docker memory. Missing provider or Docker telemetry remains `null`.

The default target is restricted to local HTTP. Use `--allow-nonlocal` only for
an explicitly approved test environment; never point this runner at production
without a separate change review.
