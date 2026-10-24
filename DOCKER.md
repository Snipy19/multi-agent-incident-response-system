# Docker development

The project can run locally in a reproducible container. Docker does not copy
`.env`, OAuth credentials, runtime reports, or the local SQLite database into
the image.

## Prerequisites

Install Docker Desktop, then confirm:

```powershell
docker --version
docker compose version
```

## Start the service

Ensure `.env` contains the required local credentials, then run:

```powershell
docker compose up --build
```

The image uses a CPU-only PyTorch wheel because the current deployment target
does not provide an NVIDIA GPU. Test-only packages are kept out of the image,
which reduces dependency downloads and runtime image size.

Open the website at:

```text
http://127.0.0.1:8000/ui/login.html
```

The API health check is available at:

```text
http://127.0.0.1:8000/
```

Container readiness, including a real persistence check, is available at:

```text
http://127.0.0.1:8000/health/ready
```

The container healthcheck uses `/health/ready`; `/health/live` is a
process-only liveness probe.

## Publishing a release image

The release workflow publishes a versioned image to GitHub Container Registry
only when a version tag is pushed. Ordinary commits do not publish or deploy
anything.

```powershell
git tag v0.1.0
git push origin v0.1.0
```

The image is published as:

```text
ghcr.io/snipy19/multi-agent-incident-response-system:v0.1.0
```

AWS deployment is intentionally not claimed here. ECS/EKS service details,
region, networking, database, and secrets must be configured before a deploy
workflow can safely roll out this image.

## Stop the service

```powershell
docker compose down
```

The current Compose file mounts `./db` for local SQLite persistence. During
AWS deployment, remove that mount and set `DATABASE_URL` to the RDS
PostgreSQL connection string instead. Leaving `DATABASE_URL` empty keeps the
local SQLite path for development.

When `ENVIRONMENT=production`, startup requires the real JWT, PostgreSQL,
Groq, Google OAuth, email, and CORS settings. Localhost origins, wildcard CORS,
SQLite, or missing credentials fail fast instead of allowing a partially fake
production deployment to start.

For a split deployment, set `ANALYSIS_WORKER_ENABLED=false` on the API service
and run the same image with:

```text
python -m services.worker_runner
```

The worker consumes the durable analysis queue from the shared database. The
default remains enabled for the local one-container workflow.
