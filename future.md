# Future scope and project rules

This file is the source of truth for future work on the Incident Response
Console. Read it before making a major change. It prevents the project from
being described as more complete than it is and prevents deferred deployment
work from being started accidentally.

## Current truth: 2026-10-24

The following is implemented and must not be re-planned as if it were missing:

- The application runs locally with Docker Compose at `http://127.0.0.1:8000`.
- Local persistence is SQLite in the mounted `./db` directory.
- The default local workflow runs the API and durable analysis worker in one
  container. A standalone worker entry point also exists for later scaling.
- The analysis pipeline uses the configured LLM and the checked-in FAISS/RAG
  index. It does not claim that an LLM answer is verified production truth.
- Submitted logs are checked for passwords, API keys, tokens, and personal
  email addresses before analysis.
- Authentication uses password login, Google token verification, HttpOnly
  cookies, logout, password reset OTP email, ownership checks, and login/OTP
  rate limits.
- Health endpoints, security headers, request IDs, structured timing logs,
  durable analysis jobs, report export, and incident deletion are implemented.
- GitHub Actions runs Python tests, dependency checks, a real PostgreSQL
  service-container compatibility test, and a Docker image build.
- The tag-only release workflow publishes an image to GHCR. It does not deploy
  AWS or change a running environment.

## Explicitly deferred: do not do this now

- Do **not** migrate the active application from SQLite to RDS PostgreSQL.
- Do **not** remove the local `./db` volume or change the local `.env` to an RDS
  connection string.
- Do **not** claim that a PostgreSQL CI service is an RDS migration. It only
  proves that the optional PostgreSQL adapter remains compatible.
- Do **not** deploy to AWS, add a production domain, or configure HTTPS until
  the deployment phase is explicitly started.
- Do **not** push a version tag or publish a release image unless the release
  is explicitly requested.
- Do **not** add fake SMTP, fake OAuth, fake metrics, fake incident data, or
  deterministic substitute answers to make a feature look complete.

SQLite is the active backend for now. The optional PostgreSQL adapter may stay
in the repository for compatibility testing, but it is dormant in local
development and is not evidence that production data has moved.

## Completed work that should remain protected

- CPU-only PyTorch runtime and reduced runtime dependencies.
- Container health checks using real persistence readiness.
- Evidence-grounded findings with supporting evidence, missing validation, and
  alternative explanations.
- Conservative handling of invalid or unsupported model output.
- Human-review flags for uncertain remediation.
- Secret redaction and rejection before analysis.
- Request correlation IDs without logging credentials or request bodies.
- Ownership-scoped incident deletion.
- Password-reset OTP hashing, expiry, attempt limits, and unknown-user checks.
- Login throttling by username and client IP.
- Production configuration fail-fast checks (to be used only when a real
  production environment exists).

## Ordered future work

### Phase 0: repeatable manual acceptance

Before every major change:

1. Confirm the worktree and current branch are understood.
2. Start Docker only when needed and verify `/health/live` and `/health/ready`.
3. Test login, logout, password reset with a real configured mailbox, and the
   sensitive-log rejection using redacted input.
4. Submit a real, redaction-safe sample incident and inspect the live pipeline,
   findings, confidence basis, human-review status, and report downloads.
5. Verify that the result is persisted and that one user cannot delete another
   user's incident.
6. Run `docker compose down` after manual testing to release Docker RAM, CPU,
   and disk resources.

### Phase 1: evidence quality, speed, and observability

- Add LangSmith or an equivalent real tracing integration only when its
  credentials, retention policy, and cost controls are configured.
- Track real request duration, queue wait, LLM latency, token usage, retries,
  failure rates, and per-analysis cost. Do not invent values when telemetry is
  unavailable.
- Benchmark analysis with reproducible workloads of 1, 10, 25, 50, and 100
  investigator targets. Record hardware, model, prompt size, latency, memory,
  and cost in the repository.
- Improve large-log processing by normalizing timestamps, deduplicating exact
  repeats, grouping related events, limiting context by evidence value, and
  preserving the original log for audit. Never silently discard evidence.
- Add cancellation, timeout, retry, idempotency, and partial-result behavior
  for long analyses.
- Review report HTML, Markdown, text, and PDF rendering for Unicode, timezone,
  page breaks, escaping, repeated confidence labels, and missing confidence
  rationale.
- Replace remaining presentation-only wording such as “model estimate” with
  wording that clearly separates model estimates from verified evidence.

### Phase 2: scalable worker architecture

- Move from the local SQLite-backed worker arrangement to a real shared queue
  only after measured workloads justify it.
- Select and document one queue technology (for example SQS, Redis/RQ, or
  Celery) instead of adding multiple overlapping systems.
- Make jobs idempotent, retryable, observable, and safe across multiple API and
  worker replicas.
- Move rate-limit and job-coordination state to shared infrastructure before
  running more than one application replica.

### Phase 3: database migration (future, explicit approval required)

This phase is intentionally not active.

- Inventory SQLite tables, indexes, row counts, retention requirements, and
  data ownership.
- Create and test a repeatable backup and migration tool.
- Provision PostgreSQL in a non-production environment first; do not point the
  local app at RDS as an experiment.
- Validate schema, migrations, timestamps, OTP behavior, rate limits, queue
  heartbeats, incident ownership, exports, and rollback.
- Run a canary with real credentials and monitored traffic.
- Only after explicit approval, switch `DATABASE_URL`, remove the SQLite
  production path, and document the rollback plan.

### Phase 4: real deployment and security

- Choose the runtime (ECS/Fargate, EKS, or another explicitly selected target).
- Configure networking, private subnets, security groups, database access,
  health checks, autoscaling, backups, retention, and alerting.
- Use a real secret manager and short-lived CI/OIDC credentials; never commit
  `.env`, OAuth secrets, SMTP passwords, API keys, or database URLs.
- Define CI/CD promotion stages: test, build, scan, publish, deploy to staging,
  smoke test, approval, production deploy, rollback.
- Add image/dependency/security scanning and a documented incident response
  procedure for the application itself.
- Add HTTPS and a custom domain only after the service is actually deployed.

### Phase 5: product and frontend polish

- Build the final responsive visual design, including the requested 3D styling,
  without reducing accessibility or performance.
- Add password show/hide controls and a real password-strength indicator based
  on explicit password rules. The indicator must guide the user, not claim a
  cryptographic strength score it cannot measure.
- Test keyboard navigation, focus states, screen-reader labels, mobile layout,
  loading/error states, and safe handling of expired sessions.

### Phase 6: documentation and delivery

- Keep the README aligned with the actual local run path and current limits.
- Add an architecture diagram showing API, worker, LLM, RAG, database, email,
  and future deployment boundaries.
- Publish benchmark results, known limitations, security assumptions, and a
  short reproducible demo script.
- Add a resume/project summary only from verified capabilities and measured
  results; do not describe deferred AWS/RDS work as completed.

## Rules for future implementation

For every major change, the implementation must:

1. Inspect the current code and tests before editing.
2. Preserve existing API contracts unless a deliberate migration is approved.
3. Add or update automated tests for the changed behavior.
4. Run the relevant manual flow with Docker and a redaction-safe sample log.
5. Run the full test suite, compile check, dependency check, and `git diff --check`.
6. Commit with a precise message and push only after verification.
7. Wait for and record the GitHub Actions result, including its URL.
8. Report exactly what changed, what was verified, what remains unverified, and
   whether Docker should be shut down.

## Truth and safety rules

- LLM-generated findings are hypotheses unless the submitted evidence supports
  them; they are not live-system inspection.
- Numeric confidence is an evidence estimate, not a calibrated probability.
- CI passing means the tested code passed CI; it does not mean AWS is deployed,
  email is configured, or a recommendation was applied.
- A recommendation is advisory and must remain reviewable by an engineer.
- Synthetic benchmark labels and test fixtures must never be presented as real
  incidents or production telemetry.
- No password, API key, bearer token, OTP, OAuth secret, SMTP credential, or
  customer data belongs in a log, report, screenshot, commit, or test fixture.
- When evidence is missing, say so and return an inconclusive result instead of
  filling the gap with a confident deterministic answer.

## Next step when work resumes

The next immediate task is Phase 0 manual acceptance of the current SQLite
workflow, followed by Phase 1 latency/observability work. RDS, AWS, HTTPS, and
the production database migration remain out of scope until explicitly
requested.
