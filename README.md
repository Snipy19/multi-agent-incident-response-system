# Incident Response Console

An evidence-grounded, multi-agent incident analysis service built with
FastAPI, LangGraph, Groq, FAISS/RAG, SQLite, Docker, and GitHub Actions.

The system accepts a redaction-safe incident log, selects focused investigation
angles, runs the investigators in parallel, reconciles their findings, and
produces a reviewable remediation recommendation. It does not apply fixes to
infrastructure and does not claim that an LLM response is verified production
truth.

## Current status

The supported workflow today is local Docker development:

- API and durable analysis worker run in one Compose container by default.
- SQLite in the mounted `./db` directory is the active database.
- Groq is the configured LLM provider when `GROQ_API_KEY` is present.
- The checked-in FAISS index provides historical log-pattern context.
- Password login, Google token verification, email OTP reset, HttpOnly auth
  cookies, rate limits, request IDs, health checks, report downloads, and
  ownership-scoped deletion are implemented.
- GitHub Actions runs tests, dependency checks, PostgreSQL adapter coverage,
  and a Docker image build.
- A version-tag workflow publishes an image to GHCR; it does not deploy AWS.

PostgreSQL compatibility is tested in CI, but it is not the active local
backend and is not an RDS migration. AWS deployment, RDS, HTTPS, a custom
domain, and a shared external queue are deferred. See [future.md](future.md)
before starting any future work.

## Run locally

1. Copy `.env.example` to `.env`.
2. Add real local credentials only where the feature is being tested. Never
   commit `.env`.
3. Start Docker Desktop.
4. From PowerShell:

```powershell
docker compose up --build
```

Open the application at:

```text
http://127.0.0.1:8000/ui/login.html
```

Health endpoints:

```text
http://127.0.0.1:8000/health/live
http://127.0.0.1:8000/health/ready
```

Stop local Docker after manual testing:

```powershell
docker compose down
```

For the full Docker notes, see [DOCKER.md](DOCKER.md).

## Analysis behavior

The request path is:

1. Redact-and-reject checks inspect the submitted log for passwords, API keys,
   bearer tokens, OTPs, and personal email addresses.
2. The triage LLM decides whether the log describes an anomaly and selects
   bounded, evidence-supported investigation angles.
3. Investigators run in parallel. Each receives a focused slice of the log and
   relevant RAG context rather than an unbounded copy of the entire input.
4. The aggregator separates observed facts from hypotheses and records
   supporting evidence, missing validation, and alternatives.
5. The remediation agent proposes advisory, reviewable next actions. It does
   not execute changes.
6. Reports are rendered from structured state so exported formats do not add
   new causal claims.

When model output is invalid or evidence is insufficient, the system keeps the
result inconclusive or low-confidence. It must not fill missing evidence with
confident deterministic text.

## Configuration boundaries

Use `ENVIRONMENT=development` for the local Compose workflow. The production
configuration guardrails intentionally require real secrets, non-local CORS,
and PostgreSQL before `ENVIRONMENT=production` can start. That guardrail does
not mean a production deployment currently exists.

For a later split deployment, set `ANALYSIS_WORKER_ENABLED=false` on the API
service and run:

```text
python -m services.worker_runner
```

This is a future scaling boundary; local SQLite is not suitable as the shared
database for multiple production replicas.

## Test and validation commands

From an activated virtual environment:

```powershell
python -m pytest -q
python -m compileall -q auth.py graph.py main.py state.py agents db services utils vectorstore tests
python -m pip check
git diff --check
```

The live LLM/RAG test is opt-in and requires real credentials:

```powershell
$env:RUN_LIVE_LLM_TESTS = "1"
python -m pytest tests/test_graph_live.py -q
```

The PostgreSQL integration test is exercised by CI with a real PostgreSQL
service container. Set `TEST_DATABASE_URL` only when intentionally running
that test against a real test database. This does not move application data.

## CI/CD boundary

Pushes to `main` run the CI workflow. A `v*` tag publishes a versioned image to
GHCR. No workflow currently performs an AWS deployment or production database
migration. Those actions require infrastructure, secrets, approval gates,
rollback, and manual validation documented in [future.md](future.md).

## Security rules

- Never put passwords, API keys, OAuth secrets, SMTP credentials, OTPs, bearer
  tokens, or customer data in logs, reports, screenshots, commits, or fixtures.
- Use a real configured mailbox for OTP testing; no fake mail delivery is
  presented as a successful production flow.
- Treat numeric confidence as a model/evidence estimate, not a calibrated
  probability.
- Treat all remediation as advisory until an engineer validates it.
- Do not describe CI success, a PostgreSQL compatibility test, or an image
  publication as an AWS production deployment.

## Future work

The ordered roadmap, deferred RDS decision, manual acceptance checklist,
benchmark plan, observability work, deployment requirements, and reporting
rules are maintained in [future.md](future.md).
